import os
from stat import (
    S_IRUSR, S_IWUSR, S_IXUSR,
    S_IRGRP, S_IWGRP, S_IXGRP,
    S_IROTH, S_IWOTH, S_IXOTH
)

from textwrap import dedent
from traitlets import Bool

from .exchange import Exchange
from ..utils import get_username, check_mode, find_all_notebooks, compute_notebook_checksum

import nbformat as nbf
import json
import numpy as np
import distutils

class ExchangeSubmit(Exchange):

    strict = Bool(
        False,
        help=dedent(
            "Whether or not to submit the assignment if there are missing "
            "notebooks from the released assignment notebooks."
        )
    ).tag(config=True)

    def init_src(self):
        if self.path_includes_course:
            root = os.path.join(self.course_id, self.coursedir.assignment_id)
        else:
            root = self.coursedir.assignment_id
        self.src_path = os.path.abspath(root)
        self.coursedir.assignment_id = os.path.split(self.src_path)[-1]
        if not os.path.isdir(self.src_path):
            self.fail("Assignment not found: {}".format(self.src_path))

    def init_dest(self):
        if self.course_id == '':
            self.fail("No course id specified. Re-run with --course flag.")

        self.inbound_path = os.path.join(self.root, self.course_id, 'inbound')
        if not os.path.isdir(self.inbound_path):
            self.fail("Inbound directory doesn't exist: {}".format(self.inbound_path))
        if not check_mode(self.inbound_path, write=True, execute=True):
            self.fail("You don't have write permissions to the directory: {}".format(self.inbound_path))

        self.cache_path = os.path.join(self.cache, self.course_id)
        self.assignment_filename = '{}+{}+{}'.format(get_username(), self.coursedir.assignment_id, self.timestamp)

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

    def add_hashcode(self, notebook_file, hashcode):
        nb = nbf.v4.new_notebook()
        #notebook_file = os.path.join(self.src_path, self.coursedir.assignment_id+".ipynb")
        nbr = nbf.read(notebook_file, as_version=4)
        #hash_code = np.random.randint(0,9,6)
        #hash_str = ''.join(str(e) for e in hashcode)
        hash_str = str(hashcode)

        hashcode_cell = """<div class=\"alert alert-block alert-danger\"> \n\nIhr Haschcode: {} \n\n</div>\n\n
                   """.format(hash_str)
        # TODO: * Add time stamp to

        # check whether the hashcode has been generated before
        meta_found = False
        meta_src_idx = None
        hashcode_markdown_id = "hashcode_cell"
        for i,c in enumerate(nbr['cells']):
            curr_cel = c
            if curr_cel['cell_type'] == "markdown":
                metadata = curr_cel['metadata']
                source = curr_cel['source']
                if 'name' in metadata:
                    for meta in metadata:
                        metadata_nbgrader = metadata['name']
                        if metadata_nbgrader == hashcode_markdown_id:
                            meta_found = True
                            meta_src_idx = i

        # if meta found in nb already, then append
        # otherwise append new cell for hashcode
        if meta_found:
            nbr['cells'][meta_src_idx]['source'] = hashcode_cell
        else:    
            addition = nbf.v4.new_markdown_cell(hashcode_cell)
            addition['metadata']["name"] = hashcode_markdown_id
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

    def generate_hashcode(self,filename):
        notebook_file = os.path.join(self.src_path, self.coursedir.assignment_id+".ipynb")
        return hash_with_md5(notebook_file)

    def copy_and_overwrite_dir(self, src, dest):
        distutils.dir_util.copy_tree(src, dest)

    def copy_files(self):
        self.init_release()

        self.log.info("Copying course_dir into .temp")
        user_home_dir = os.path.abspath(os.path.join(os.path.dirname(self.src_path), '.'))
        temp_path = os.path.join(user_home_dir, ".temp", self.coursedir.assignment_id)
        self.copy_and_overwrite_dir(self.src_path, temp_path)
        
        # Original notebook file
        student_notebook_file = os.path.join(self.src_path, self.coursedir.assignment_id+".ipynb")
        hashcode = compute_notebook_checksum(student_notebook_file)
        self.log.info("Hashcode generated: {}".format(hashcode))
        
        # write hashcode to hashcoded_notebook_version
        self.log.info("Writing hashcode to .temp version")
        hashcoded_notebook_file = os.path.join(temp_path, self.coursedir.assignment_id+".ipynb")
        temp_html_file = os.path.join(temp_path, self.coursedir.assignment_id+".html")
        self.add_hashcode(hashcoded_notebook_file, hashcode)
        
        # generate html inside the original nbgrader directory     
        self.log.info("Generate html and copy html to student course dir")  
        self.generate_html(hashcoded_notebook_file, temp_html_file)
        
        # Copy html file to course_dir
        student_html_file = os.path.join(self.src_path, self.coursedir.assignment_id+".html")
        distutils.file_util.copy_file(temp_html_file, student_html_file)
        
        dest_path = os.path.join(self.inbound_path, self.assignment_filename)
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
