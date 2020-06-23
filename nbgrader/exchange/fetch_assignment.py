import os
import shutil
import glob
import copy
import nbformat

from traitlets import Bool

from .exchange import Exchange
from ..utils import check_mode
from ..preprocessors import Scramble, PermuteTasks


class ExchangeFetchAssignment(Exchange):

    replace_missing_files = Bool(False, help="Whether to replace missing files on fetch").tag(config=True)

    def _load_config(self, cfg, **kwargs):
        if 'ExchangeFetch' in cfg:
            self.log.warning(
                "Use ExchangeFetchAssignment in config, not ExchangeFetch. Outdated config:\n%s",
                '\n'.join(
                    'ExchangeFetch.{key} = {value!r}'.format(key=key, value=value)
                    for key, value in cfg.ExchangeFetchAssignment.items()
                )
            )
            cfg.ExchangeFetchAssignment.merge(cfg.ExchangeFetch)
            del cfg.ExchangeFetchAssignment

        super(ExchangeFetchAssignment, self)._load_config(cfg, **kwargs)

    def init_src(self):
        if self.coursedir.course_id == '':
            self.fail("No course id specified. Re-run with --course flag.")
        if not self.authenticator.has_access(self.coursedir.student_id, self.coursedir.course_id):
            self.fail("You do not have access to this course.")

        self.course_path = os.path.join(self.root, self.coursedir.course_id)
        self.outbound_path = os.path.join(self.course_path, 'outbound')
        self.src_path = os.path.join(self.outbound_path, self.coursedir.assignment_id)
        if not os.path.isdir(self.src_path):
            self._assignment_not_found(
                self.src_path,
                os.path.join(self.outbound_path, "*"))
        if not check_mode(self.src_path, read=True, execute=True):
            self.fail("You don't have read permissions for the directory: {}".format(self.src_path))
        # Add user to src path in order to fetch personalized assignment
        # self.src_path += '/{}'.format(os.getenv('JUPYTERHUB_USER'))

    def init_dest(self):
        if self.path_includes_course:
            root = os.path.join(self.coursedir.course_id, self.coursedir.assignment_id)
        else:
            root = self.coursedir.assignment_id
        self.dest_path = os.path.abspath(os.path.join(self.assignment_dir, root))
        if os.path.isdir(self.dest_path) and not self.replace_missing_files:
            self.fail("You already have a copy of the assignment in this directory: {}".format(root))

    def copy_if_missing(self, src, dest, ignore=None):
        filenames = sorted(os.listdir(src))
        if ignore:
            bad_filenames = ignore(src, filenames)
            filenames = sorted(list(set(filenames) - bad_filenames))

        for filename in filenames:
            srcpath = os.path.join(src, filename)
            destpath = os.path.join(dest, filename)
            relpath = os.path.relpath(destpath, os.getcwd())
            if not os.path.exists(destpath):
                if os.path.isdir(srcpath):
                    self.log.warning("Creating missing directory '%s'", relpath)
                    os.mkdir(destpath)

                else:
                    self.log.warning("Replacing missing file '%s'", relpath)
                    shutil.copy(srcpath, destpath)

            if os.path.isdir(srcpath):
                self.copy_if_missing(srcpath, destpath, ignore=ignore)

    def do_copy(self, src, dest):
        """Copy the src dir to the dest dir omitting the self.coursedir.ignore globs."""
        # Check if there is a version for the student
        if self.personalized_outbound:
            if os.path.exists(os.path.join(src, os.getenv('JUPYTERHUB_USER'))):
                src = os.path.join(src, os.getenv('JUPYTERHUB_USER'))
            else:
                self.log.warning('Using personalized outbound, but no directory for user {} exists'.format(os.getenv('JUPYTERHUB_USER')))
            
        if os.path.isdir(self.dest_path):
            self.copy_if_missing(src, dest, ignore=shutil.ignore_patterns(*self.coursedir.ignore))
        else:
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*self.coursedir.ignore))

    def do_scrambling(self, dest, student_id):
        self.log.info("Scrambling for {}".format(student_id))
        nbs = glob.glob(dest + '/*.ipynb')
        self.log.info("Found the following notebooks: {}".format(nbs))
        scrambler = Scramble(seed=hash(student_id))
        permuter = PermuteTasks(seed=hash(student_id))
        for nb_path in nbs:
            nb = nbformat.read(nb_path, as_version=4)
            if len(nb.cells) > 0 and nb.cells[0].source.startswith('%% scramble'):
                resources = {}
                nb, resources = scrambler.preprocess(nb, resources)
                nb, resources = permuter.preprocess(nb, resources)
            nbformat.write(nb, nb_path)
        self.log.info("Scrambled")

    def copy_files(self):
        self.log.info("Outbound path: "+self.outbound_path)
        
        self.log.info("Source: {}".format(self.src_path))
        self.log.info("Destination: {}".format(self.dest_path))
        self.do_copy(self.src_path, self.dest_path)
        self.do_scrambling(self.dest_path, os.getenv('JUPYTERHUB_USER'))
        self.log.info("Fetched as: {} {}".format(self.coursedir.course_id, self.coursedir.assignment_id))
