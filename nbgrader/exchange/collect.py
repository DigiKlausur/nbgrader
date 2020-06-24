import os
import glob
import shutil
import sys
from collections import defaultdict
from textwrap import dedent

from traitlets import Bool

from .exchange import Exchange
from ..utils import check_mode, parse_utc

import pandas as pd
import csv

# pwd is for matching unix names with student ide, so we shouldn't import it on
# windows machines
if sys.platform != 'win32':
    import pwd
else:
    pwd = None

def groupby(l, key=lambda x: x):
    d = defaultdict(list)
    for item in l:
        d[key(item)].append(item)
    return d


class ExchangeCollect(Exchange):

    update = Bool(
        False,
        help="Update existing submissions with ones that have newer timestamps."
    ).tag(config=True)

    check_owner = Bool(
        default_value=True,
        help="Whether to cross-check the student_id with the UNIX-owner of the submitted directory."
    ).tag(config=True)

    def _path_to_record(self, path):
        filename = os.path.split(path)[1]
        # Only split twice on +, giving three components. This allows usernames with +.
        filename_list = filename.rsplit('+', 3)
        if len(filename_list) < 3:
            self.fail("Invalid filename: {}".format(filename))
        username = filename_list[0]
        timestamp = parse_utc(filename_list[2])
        return {'username': username, 'filename': filename, 'timestamp': timestamp}

    def _sort_by_timestamp(self, records):
        return sorted(records, key=lambda item: item['timestamp'], reverse=True)

    def init_src(self):
        if self.coursedir.course_id == '':
            self.fail("No course id specified. Re-run with --course flag.")
        
        self.course_path = os.path.join(self.root, self.coursedir.course_id)
        
        # change sourse to http submit
        if self.enable_http_submit:
            self.log.info("Collecting from http submit ", self.http_submit_path)
            zipped_submission_list = [zipped_sub for zipped_sub in os.listdir(self.http_submit_path) if os.path.splitext(zipped_sub)[1] == ".zip"]
            print ("zipped submission ", zipped_submission_list)            
            self.log.info("Unpacking submission....")
            self.inbound_path = os.path.join(self.http_submit_path, 'extracted') 
            for zipped_sub in zipped_submission_list:
                sub_path = os.path.join(self.http_submit_path, zipped_sub)
                dest_path = os.path.join(self.inbound_path, os.path.splitext(zipped_sub)[0])
                dest_path = os.path.join(self.http_submit_path, dest_path)
                shutil.unpack_archive(sub_path, dest_path, "zip")
        elif self.enable_k8s_submit:
            self.inbound_path = os.path.join(self.course_path, self.k8s_inbound) 
        else:
            self.inbound_path = os.path.join(self.course_path, 'inbound')

        if not os.path.isdir(self.inbound_path):
            self.fail("Course not found: {}".format(self.inbound_path))
        
        if not check_mode(self.inbound_path, read=True, execute=True):
            self.fail("You don't have read permissions for the directory: {}".format(self.inbound_path))

        #look into student id dir if submission dir is restricted
        if self.restrict_submit:
            self.log.info("Collecting from restricted submit dirs")
            #skip dir that contains nbgrader submit patter, take dir with username only e.g. mwasil2s
            submit_dirs = [username for username in os.listdir(self.inbound_path) if "+" not in username and 
                           os.path.isdir(os.path.join(self.inbound_path, username))]
            self.log.info("Submission dirs {}".format(submit_dirs))

            self.src_records = []
            for username in submit_dirs:
                submit_path = os.path.join(self.inbound_path, username)
                self.log.info("Assignment id: {}".format(self.coursedir.assignment_id))
                pattern = os.path.join(submit_path, '{}+{}+*'.format(username, self.coursedir.assignment_id))
                records = [self._path_to_record(f) for f in glob.glob(pattern)]
                self.log.info("[{}] Total submission: ".format(username, len(records)))
                #update file path
                for i,record in enumerate(records):
                    filename = os.path.join(username,record['filename'])
                    records[i]['filename'] = filename
                
                usergroups = groupby(records, lambda item: item['username'])
                user_record = self._sort_by_timestamp(records)
                self.log.info("[{}]: {}".format(username, user_record))
                if len(user_record) > 0:
                    self.src_records.append(user_record[0])

        else:
            student_id = self.coursedir.student_id if self.coursedir.student_id else '*'
            pattern = os.path.join(self.inbound_path, '{}+{}+*'.format(student_id, self.coursedir.assignment_id))
        
            records = [self._path_to_record(f) for f in glob.glob(pattern)]
            usergroups = groupby(records, lambda item: item['username'])
            self.src_records = [self._sort_by_timestamp(v)[0] for v in usergroups.values()]

    def init_dest(self):
        pass

    def copy_files(self):
        if len(self.src_records) == 0:
            self.log.warning("No submissions of '{}' for course '{}' to collect".format(
                self.coursedir.assignment_id,
                self.coursedir.course_id))
        else:
            self.log.info("Processing {} submissions of '{}' for course '{}'".format(
                len(self.src_records),
                self.coursedir.assignment_id,
                self.coursedir.course_id))

        user_infos = []
        for rec in self.src_records:
            student_id = rec['username']
            src_path = os.path.join(self.inbound_path, rec['filename'])

            # Cross check the student id with the owner of the submitted directory
            if self.check_owner and pwd is not None: # check disabled under windows
                try:
                    owner = pwd.getpwuid(os.stat(src_path).st_uid).pw_name
                except KeyError:
                    owner = "unknown id"
                if student_id != owner:
                    self.log.warning(dedent(
                        """
                        {} claims to be submitted by {} but is owned by {}; cheating attempt?
                        you may disable this warning by unsetting the option CollectApp.check_owner
                        """).format(src_path, student_id, owner))

            dest_path = self.coursedir.format_path(self.coursedir.submitted_directory, student_id, self.coursedir.assignment_id)
            if not os.path.exists(os.path.dirname(dest_path)):
                os.makedirs(os.path.dirname(dest_path))

            hashed_dest_path = self.coursedir.format_path("hashed_submission", student_id, self.coursedir.assignment_id)
            if not os.path.exists(os.path.dirname(hashed_dest_path)):
                os.makedirs(os.path.dirname(hashed_dest_path))

            copy = False
            updating = False
            if os.path.isdir(dest_path):
                existing_timestamp = self.coursedir.get_existing_timestamp(dest_path)
                new_timestamp = rec['timestamp']
                if self.update and (existing_timestamp is None or new_timestamp > existing_timestamp):
                    copy = True
                    updating = True
            else:
                copy = True

            self.log.info ("src: {}".format(src_path))
            self.log.info ("dst: {}".format(dest_path))
            if copy:
                if updating:
                    self.log.info("Updating submission: {} {}".format(student_id, self.coursedir.assignment_id))
                    shutil.rmtree(dest_path)
                    self.log.info("Updating hashed_submission directory")
                    if os.path.isdir(hashed_dest_path):
                        shutil.rmtree(hashed_dest_path)
                else:
                    self.log.info("Collecting submission: {} {}".format(student_id, self.coursedir.assignment_id))

                if not self.do_copy(src_path, dest_path):
                    self.log.error("Inbound path should be rwx by instructor: sudo chmod -R o+rwx {}".format(self.inbound_path))
                    return 
                
                # Create hashed_submission
                self.do_copy(src_path, hashed_dest_path)
            else:
                if self.update:
                    self.log.info("No newer submission to collect: {} {}".format(
                        student_id, self.coursedir.assignment_id
                    ))
                else:
                    self.log.info("Submission already exists, use --update to update: {} {}".format(
                        student_id, self.coursedir.assignment_id
                    ))

            user_info = self.extract_user_info(dest_path, student_id)
            if user_info is not None:
                user_infos.append(user_info)

        #Create hashcode list            
        if len(user_infos) > 0: 
            self.log.info("Creating hashcode list")
            csv_filename = "{}_{}_hashcode_list.csv".format(self.coursedir.course_id, self.coursedir.assignment_id)
            html_filename = "{}_{}_hashcode_list.html".format(self.coursedir.course_id, self.coursedir.assignment_id)
            hashcode_list_path = os.path.join(self.coursedir.root, self.coursedir.submitted_directory)
            csv_file_dest_path = os.path.join(hashcode_list_path, csv_filename)
            html_file_dest_path = os.path.join(hashcode_list_path, html_filename)
            self.create_hashcode_list(user_infos, hashcode_list_path, filename=csv_filename)

            # Load csv and create html
            self.log.info("Creating {}".format(html_file_dest_path))
            data = pd.read_csv(csv_file_dest_path) 
            data.to_html(html_file_dest_path, justify='center')

            # Copy hashcode_list to /tmp for the other graders
            #tmp_html_file_dest_path = os.path.join('/tmp', html_filename)
            #data.to_html(tmp_html_file_dest_path, justify='center')
        else:
            self.log.info("Userinfo not found, hashcode list is not generated")

    def extract_user_info(self, info_path, username):
        file_info_path = os.path.join(info_path, username+"_info.txt")
        if os.path.isfile(file_info_path):
            try: 
                with open(file_info_path) as f:
                    user_info = f.readlines()
            finally:  
                f.close()

            user_info = [x.strip().split(': ')[1] for x in user_info]
            return user_info
        else:
            return

    def create_hashcode_list(self, user_infos, list_dest_path, filename='hashcode_list.csv'):
        username_field = "Username"
        hashcode_field = "Hashcode"
        timestamp_field = "Timestamp"

        file_dest_path = os.path.join(list_dest_path, filename)
        # Check if the hashcode list exists
        if not os.path.exists(file_dest_path):
            self.log.info("{} does not exist".format(file_dest_path))
            self.log.info("Creating {}".format(file_dest_path))
            with open(file_dest_path, 'w') as csvfile:
                fieldnames = ['Username', 'Hashcode', 'Timestamp']
        
        if os.path.exists(file_dest_path):
            self.log.info("Hashcode list available")
            self.log.info("Opening {}".format(file_dest_path))
            with open(file_dest_path, 'w') as csvfile:
                fieldnames = ['Username', 'Hashcode', 'Timestamp']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for uinfo in user_infos:
                    writer.writerow({username_field:uinfo[0],
                                    hashcode_field:uinfo[1],
                                    timestamp_field:uinfo[2]})
