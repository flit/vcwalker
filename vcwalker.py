#!/usr/bin/python

import os
import subprocess
import logging
from coloredlogger import ColoredLogger
import argparse


class VCWalker(object):

    auto_upgrade = False

    def __init__(self, auto_update, auto_upgrade, ignore_added):
        self.auto_upgrade = auto_upgrade
        self.auto_update = auto_update
        self.ignore_added = ignore_added
        self.logger = logging.getLogger("walker")

    def walkdir(self, rootdir):
        output = {}
        for dirpath, subdirs, files in os.walk(rootdir, topdown=True):
            if '.svn' in subdirs:
                # if this is the root of a svn dir, don't visit any subdirs
                subdirs[:] = []
                output[dirpath] = self.checkvc(dirpath, 'svn')
            if '.git' in subdirs:
                # here, it is not necessary, but we do it anyway to reduce search time
                # note that this will cause repos to be ignored if they are sub-repos of git repos
                subdirs[:] = []
                output[dirpath] = self.checkvc(dirpath, 'git')

            # we are not interested in hidden directories.
            subdirs[:] = [x for x in subdirs if not x.startswith('.')]
        return output

    def checkvc(self, path, type, try_update = True):
        if type == 'git':
            (status, files) = self._git_get_status(path)
        else:
            (status, files) = self._svn_get_status(path)

        if status == None:
            self.logger.info(path)
            self.logger.warning("Could not check this repository.")
            return

        output = False
        if 'needs-push' in status:
            self.logger.info(path)
            output = True
            self.logger.info("Needs Push.")

        if 'needs-pull' in status:
            if not output:
                self.logger.info(path)
                output = True
            if type == 'git':
                self.logger.info("Needs Pull.")
            else:
                self.logger.info("Needs Update.")

        if 'diverged' in status:
            if not output:
                self.logger.info(path)
                output = True
            self.logger.info("Needs Merge.")

        if 'modified' in status:
            if not output:
                self.logger.info(path)
                output = True
            self.logger.info("Locally modified files:")
            for f in files['modified']:
                self.logger.info("  - %s" % f)

        if 'added' in status:
            if not output:
                self.logger.info(path)
                output = True
            self.logger.info("New local files:")
            for f in files['added']:
                self.logger.info("  - %s" % f)

        if 'needs-pull' in status and try_update and self.auto_update:
            if type == 'git':
                self._git_update(path)
            else:
                self._svn_update(path)
                return self.checkvc(path, type, False)

        return status

    def _git_get_status(self, path):
        out_status = []
        out_files = {
            'modified': [],
            'added': []
        }

        try: 
            subprocess.check_output(["git", "-C", path, "remote", "update"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            self.logger.error(e.output)
            return (None, e.output)

        # Use the strategy described in https://stackoverflow.com/questions/3258243/git-check-if-pull-needed to check if a pull is needed
        try: 
            local = subprocess.check_output(["git", "-C", path, "rev-parse", "@"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            self.logger.error(e.output)
            return (None, e.output)
        
        try: 
            remote = subprocess.check_output(["git", "-C", path, "rev-parse", "@{u}"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            self.logger.error(e.output)
            return (None, e.output)
        
        try: 
            base = subprocess.check_output(["git", "-C", path, "merge-base", "@", "@{u}"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            self.logger.error(e.output)
            return (None, e.output)

        if local == remote:
            pass
        elif local == base:
            out_status.append("needs-pull")
        elif remote == base:
            out_status.append("needs-push")
        else:
            out_status.append("diverged")
          
        # Now check for local modifications
        try: 
            status = subprocess.check_output(["git", "-C", path, "status", "--porcelain"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            self.logger.error(e.output)
            return (None, e.output)

        for line in status.split("\n")[:-1]:
            self.logger.debug("Checking: >>%s<<" % line)
            if line[1] in 'MARCD':
                if not 'modified' in out_status:
                    out_status.append("modified")
                out_files['modified'].append(os.path.join(path, line[3:]))
            if line[0:2] == '??' and not self.ignore_added:
                if not 'added' in out_status:
                    out_status.append("added")
                out_files['added'].append(os.path.join(path, line[3:]))

        return (out_status, out_files)

    def _git_update(self, path):
        try: 
            subprocess.check_output(["git", "-C", path, "pull"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            self.logger.error(e.output)
        
  
    def _svn_get_status(self, path):
        out_status = []
        out_files = {
            'modified': [],
            'added': []
        }
        try: 
            status = subprocess.check_output(["svn", "status", "-u", path], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            if 'E155036' in e.output:
                if self.auto_upgrade:
                    self.logger.warn("Upgrading SVN version.")
                    if self._svn_upgrade(path):
                        return self._svn_get_status(path)
                self.logger.error("SVN version is too old.")
                return (None, "SVN version outdated.")
            else:
                self.logger.error(e.output)
                return (None, e.output)

        self.logger.debug("Status: %s" % status)
        for line in status.split('\n')[:-1]:
            self.logger.debug("Checking: >>%s<<" % line)
            if line[0] in 'ACDMR!':
                if not 'modified' in out_status:
                    out_status.append("modified")
                out_files['modified'].append(line[21:])

            elif line[0] == '?' and not self.ignore_added:
                if not 'added' in out_status:
                    out_status.append("added")
                out_files['added'].append(line[21:])

            if line[8] == '*':
                if not "needs-pull" in out_status:
                    out_status.append("needs-pull")

        return (out_status, out_files)

    def _svn_upgrade(self, path):
        try: 
            status = subprocess.check_output(["svn", "upgrade", path], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            logger.error(e.output)
            return False
        return True

    def _svn_update(self, path):
        try: 
            status = subprocess.check_output(["svn", "update", path], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError, e:
            logger.error(e.output)
 
    def list(self, list):
        print "# <-- remote changes; --> local changes; |--| diverged; M modified files; A added files; E error."
        for path, result in list.items():
            if result == []:
                continue
            if result == None:
                a, b, c, d = " ", "E", "E", " "
            else:
                a = "|" if "diverged" in result else ("<" if "needs-pull" in result else " ")
                b = "M" if "modified" in result else "-"
                c = "A" if "added" in result else "-"
                d = "|" if "diverged" in result else (">" if "needs-push" in result else " ")

            print " %s%s%s%s  %s" % (a, b, c, d, path)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description = "Recursively find GIT and SVN repositories in a given path and check if remote or local files need updates.")
    parser.add_argument('--update', '-u', dest="auto_update", action="store_true", help="Perform a git pull or svn update if a repository is found to be outdated.")
    parser.add_argument('--upgrade', dest="auto_upgrade", action="store_true", help="Perform a svn upgrade if necessary (outdated SVN data format version in repository).")
    parser.add_argument('--ignore-added', '-n', dest="ignore_added", action="store_true", help="Ignore files added in the local file system.")
    parser.add_argument('--verbose', '-v', dest="verbose", default=0, action="count", help="Output all messages about single repositories. Use twice for debug output.")
    parser.add_argument('--no-color', dest="no_color", action="store_true", help="Use no color in logging output.")
    parser.add_argument('--no-list', dest="list", action="store_false", help="Don't summarize the results.")
    parser.add_argument('path', nargs="*", default=["."], help="Paths to search for repositories (Default: Working Directory).")
    args = parser.parse_args()

    if not args.no_color:
        logging.setLoggerClass(ColoredLogger)

    logging.getLogger('walker').setLevel({
        0: logging.FATAL,
        1: logging.INFO,
        2: logging.DEBUG
    }[args.verbose])

    walker = VCWalker(args.auto_update, args.auto_upgrade, args.ignore_added)

    result = {}
    for d in args.path:
        result.update(walker.walkdir(d))

    if args.list:
        walker.list(result)
