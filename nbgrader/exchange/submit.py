import base64
import os
from stat import (
    S_IRUSR, S_IWUSR, S_IXUSR,
    S_IRGRP, S_IWGRP, S_IXGRP,
    S_IROTH, S_IWOTH, S_IXOTH
)

from textwrap import dedent
from traitlets import Bool

from .exchange import Exchange
from ..utils import get_username, check_mode, find_all_notebooks
from ..utils import compute_hashcode

import nbformat as nbf
import json
import numpy as np
import distutils
import glob

class ExchangeSubmit(Exchange):

    strict = Bool(
        False,
        help=dedent(
            "Whether or not to submit the assignment if there are missing "
            "notebooks from the released assignment notebooks."
        )
    ).tag(config=True)

    add_random_string = Bool(
        True,
        help=dedent(
            "Whether to add a random string on the end of the submission."
        )
    ).tag(config=True)

    def init_src(self):
        if self.path_includes_course:
            root = os.path.join(self.course_id, self.coursedir.assignment_id)
            other_path = os.path.join(self.course_id, "*")
        else:
            root = self.coursedir.assignment_id
            other_path = "*"
        self.src_path = os.path.abspath(root)
        self.coursedir.assignment_id = os.path.split(self.src_path)[-1]
        if not os.path.isdir(self.src_path):
            self._assignment_not_found(self.src_path, os.path.abspath(other_path))

    def init_dest(self):
        if self.course_id == '':
            self.fail("No course id specified. Re-run with --course flag.")

        self.inbound_path = os.path.join(self.root, self.course_id, 'inbound')
        if not os.path.isdir(self.inbound_path):
            self.fail("Inbound directory doesn't exist: {}".format(self.inbound_path))
        if not check_mode(self.inbound_path, write=True, execute=True):
            self.fail("You don't have write permissions to the directory: {}".format(self.inbound_path))

        self.cache_path = os.path.join(self.cache, self.course_id)
        if self.add_random_string:
            random_str = base64.urlsafe_b64encode(os.urandom(9)).decode('ascii')
            self.assignment_filename = '{}+{}+{}+{}'.format(
                get_username(), self.coursedir.assignment_id, self.timestamp, random_str)
        else:
            self.assignment_filename = '{}+{}+{}'.format(
                get_username(), self.coursedir.assignment_id, self.timestamp)

    def init_release(self):
        if self.course_id == '':
            self.fail("No course id specified. Re-run with --course flag.")

        course_path = os.path.join(self.root, self.course_id)
        outbound_path = os.path.join(course_path, 'outbound')
        self.release_path = os.path.join(outbound_path, self.coursedir.assignment_id)
        if not os.path.isdir(self.release_path):
            self.fail("Assignment not found: {}".format(self.release_path))
        if not check_mode(self.release_path, read=True, execute=True):
            self.fail("You don't have read permissions for the directory: {}".format(self.release_path))

    def check_filename_diff(self):
        released_notebooks = find_all_notebooks(self.release_path)
        submitted_notebooks = find_all_notebooks(self.src_path)

        # Look for missing notebooks in submitted notebooks
        missing = False
        release_diff = list()
        for filename in released_notebooks:
            if filename in submitted_notebooks:
                release_diff.append("{}: {}".format(filename, 'FOUND'))
            else:
                missing = True
                release_diff.append("{}: {}".format(filename, 'MISSING'))

        # Look for extra notebooks in submitted notebooks
        extra = False
        submitted_diff = list()
        for filename in submitted_notebooks:
            if filename in released_notebooks:
                submitted_diff.append("{}: {}".format(filename, 'OK'))
            else:
                extra = True
                submitted_diff.append("{}: {}".format(filename, 'EXTRA'))

        if missing or extra:
            diff_msg = (
                "Expected:\n\t{}\nSubmitted:\n\t{}".format(
                    '\n\t'.join(release_diff),
                    '\n\t'.join(submitted_diff),
                )
            )
            if missing and self.strict:
                self.fail(
                    "Assignment {} not submitted. "
                    "There are missing notebooks for the submission:\n{}"
                    "".format(self.coursedir.assignment_id, diff_msg)
                )
            else:
                self.log.warning(
                    "Possible missing notebooks and/or extra notebooks "
                    "submitted for assignment {}:\n{}"
                    "".format(self.coursedir.assignment_id, diff_msg)
                )

    def add_text_to_cell(self, notebook_file, text, cell_id="hashcode_cell", msg="Ihr Hashcode"):
        nb = nbf.v4.new_notebook()
        nbr = nbf.read(notebook_file, as_version=4)
        hash_str = str(text)
        cell_content = """<div class=\"alert alert-block alert-danger\"> \n\n{}: </br><h1>{}</h1> \n\n</div>\n\n
                   """.format(msg, hash_str)
         
        # check whether the hashcode has been generated before
        meta_found = False
        meta_src_idx = None
        cell_markdown_id = cell_id
        for i,c in enumerate(nbr['cells']):
            curr_cel = c
            if curr_cel['cell_type'] == "markdown":
                metadata = curr_cel['metadata']
                source = curr_cel['source']
                if 'name' in metadata:
                    for meta in metadata:
                        metadata_nbgrader = metadata['name']
                        if metadata_nbgrader == cell_markdown_id:
                            meta_found = True
                            meta_src_idx = i

        # if meta found in nb already, then append
        # otherwise append new cell for hashcode
        if meta_found:
            nbr['cells'][meta_src_idx]['source'] = cell_content
        else:    
            addition = nbf.v4.new_markdown_cell(cell_content)
            addition['metadata']["name"] = cell_markdown_id
            addition['metadata']["deletable"] = False
            addition['metadata']["editable"] = False
            nbr['cells'].append(addition)

        # Write the updated notebook with hashcode
        f = None
        try:
            f = open(notebook_file, 'w')
            nbf.write(nbr, f)
        finally:
            if f is not None:
                f.close()

    def generate_html(self, hashcoded_notebook_file, html_file):
        print("Convert to html using nbconvert")
        print ("GENERATE: ",html_file)
        os.system('jupyter nbconvert --to html {} {}'.format(hashcoded_notebook_file, html_file))

    def copy_and_overwrite_dir(self, src, dest):
        distutils.dir_util.copy_tree(src, dest)
        
    def copy_files(self):
        self.init_release()

        student_notebook_file = os.path.join(self.src_path, self.coursedir.assignment_id+".ipynb")
        #check notebook exists
        if os.path.isfile(student_notebook_file):
            # Add time stamp to original notebook
            self.add_text_to_cell(student_notebook_file, self.timestamp, cell_id="timestamp_cell", msg="Timestamp")

            self.log.info("Copying course_dir into .temp")
            user_home_dir = os.path.abspath(os.path.join(os.path.dirname(self.src_path), '.'))
            temp_path = os.path.join(user_home_dir, ".temp", self.coursedir.assignment_id)
            self.copy_and_overwrite_dir(self.src_path, temp_path)

            # Compute stamped original notebook
            hashcode = compute_hashcode(student_notebook_file, method='sha1')
            cutsize = 20
            hashcode = hashcode[:cutsize]
            hashcode = list(hashcode)
            hashcode = str(''.join(hashcode[0:5])+"-"+''.join(hashcode[5:10])+"-"+''.join(hashcode[10:15])+"-"+''.join(hashcode[15:20]))
            self.log.info("Hashcode generated: {}".format(hashcode))

            # Generate file in which file name is mwasil2s_info.txt
            with open(os.path.join(self.src_path, "{}_info.txt".format(get_username())), "w") as fh:
                fh.write("Username: {}\n".format(get_username()))
                fh.write("Hashcode: {}\n".format(hashcode))
                fh.write("Timestamp: {}\n".format(self.timestamp))
            
            # write hashcode to hashcoded_notebook_version
            self.log.info("Writing hashcode to .temp version")
            hashcoded_notebook_file = os.path.join(temp_path, self.coursedir.assignment_id+".ipynb")
            temp_html_file = os.path.join(temp_path, self.coursedir.assignment_id+".html")
            self.add_text_to_cell(hashcoded_notebook_file, hashcode, cell_id="hashcode_cell", msg="Ihr Hashcode")
            
            # generate html inside the original nbgrader directory     
            self.log.info("Generate html and copy html to student course dir")  
            self.generate_html(hashcoded_notebook_file, temp_html_file)
            
            # Copy html file to course_dir
            # Differentiate between the nb file name and the html version with hashcode to avoid conflict when generating feedback
            html_suffix_file = "hashcode"
            student_html_file = os.path.join(self.src_path, self.coursedir.assignment_id+"_{}.html".format(html_suffix_file))
            distutils.file_util.copy_file(temp_html_file, student_html_file)

        dest_path = os.path.join(self.inbound_path, self.assignment_filename)
        if self.add_random_string:
            cache_path = os.path.join(self.cache_path, self.assignment_filename.rsplit('+', 1)[0])
        else:
            cache_path = os.path.join(self.cache_path, self.assignment_filename)

        self.log.info("Source: {}".format(self.src_path))
        self.log.info("Destination: {}".format(dest_path))

        # copy to the real location
        self.check_filename_diff()
        self.do_copy(self.src_path, dest_path)
        with open(os.path.join(dest_path, "timestamp.txt"), "w") as fh:
            fh.write(self.timestamp)
        self.set_perms(
            dest_path,
            fileperms=(S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH),
            dirperms=(S_IRUSR | S_IWUSR | S_IXUSR | S_IRGRP | S_IXGRP | S_IROTH | S_IXOTH))

        # Make this 0777=ugo=rwx so the instructor can delete later. Hidden from other users by the timestamp.
        os.chmod(
            dest_path,
            S_IRUSR|S_IWUSR|S_IXUSR|S_IRGRP|S_IWGRP|S_IXGRP|S_IROTH|S_IWOTH|S_IXOTH
        )

        # also copy to the cache
        if not os.path.isdir(self.cache_path):
            os.makedirs(self.cache_path)
        self.do_copy(self.src_path, cache_path)
        with open(os.path.join(cache_path, "timestamp.txt"), "w") as fh:
            fh.write(self.timestamp)

        self.log.info("Submitted as: {} {} {}".format(
            self.course_id, self.coursedir.assignment_id, str(self.timestamp)
        ))
