#!/usr/bin/env python3

import os
import subprocess
import logging
from coloredlogger import ColoredLogger
import argparse
import json
import termios
import fcntl
import sys

# from https://stackoverflow.com/questions/983354/how-do-i-make-python-to-wait-for-a-pressed-key
def read_single_keypress():
    """Waits for a single keypress on stdin.

    This is a silly function to call if you need to do it a lot because it has
    to store stdin's current setup, setup stdin for reading single keystrokes
    then read the single keystroke then revert stdin back after reading the
    keystroke.

    Returns the character of the key that was pressed (zero on
    KeyboardInterrupt which can happen when a signal gets handled)

    """

    fd = sys.stdin.fileno()
    # save old state
    flags_save = fcntl.fcntl(fd, fcntl.F_GETFL)
    attrs_save = termios.tcgetattr(fd)
    # make raw - the way to do this comes from the termios(3) man page.
    attrs = list(attrs_save) # copy the stored version to update
    # iflag
    attrs[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK
                  | termios.ISTRIP | termios.INLCR | termios. IGNCR
                  | termios.ICRNL | termios.IXON )
    # oflag
    attrs[1] &= ~termios.OPOST
    # cflag
    attrs[2] &= ~(termios.CSIZE | termios. PARENB)
    attrs[2] |= termios.CS8
    # lflag
    attrs[3] &= ~(termios.ECHONL | termios.ECHO | termios.ICANON
                  | termios.ISIG | termios.IEXTEN)
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    # turn off non-blocking
    fcntl.fcntl(fd, fcntl.F_SETFL, flags_save & ~os.O_NONBLOCK)
    # read a single keystroke
    try:
        ret = sys.stdin.read(1) # returns a single character
    except KeyboardInterrupt:
        ret = 0
    finally:
        # restore old state
        termios.tcsetattr(fd, termios.TCSAFLUSH, attrs_save)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags_save)
    return ret

class VCWalker(object):

    auto_upgrade = False

    def __init__(self, auto_update, auto_upgrade, ignore_added, interactive_add_ignore, settingsfile, launch_shell, depth):
        self.auto_upgrade = auto_upgrade
        self.auto_update = auto_update
        self.ignore_added = ignore_added
        self.interactive_add_ignore = interactive_add_ignore
        self.logger = logging.getLogger("walker")
        self.noaction_files = []
        self.settingsfile = settingsfile
        self.launch_shell = launch_shell
        self.shell = os.environ.get("SHELL", "/bin/bash")
        self.depth = depth

        if self.settingsfile != None and os.path.exists(self.settingsfile):
            input = json.loads(open(self.settingsfile).read())
            self.skip_files = input['skip_files']
            self.skip_repositories = input['skip_repositories']
        else:
            self.skip_files = []
            self.skip_repositories = []

    def shutdown(self):
        if self.settingsfile == None:
            return
        output = {
            'skip_files': self.skip_files,
            'skip_repositories': self.skip_repositories
        }
        open(self.settingsfile, 'w').write(json.dumps(output, indent=4, separators=(',', ': ')))

    def walkdir(self, rootdir):
        absroot = os.path.abspath(rootdir)
        absrootlen = len(absroot)
        output = {}
        for dirpath, subdirs, files in os.walk(absroot, topdown=True):
            if dirpath in self.skip_repositories:
                self.logger.info("Skipping %s" % dirpath)
                continue
            if '.svn' in subdirs:
                # if this is the root of a svn dir, don't visit any subdirs
                subdirs[:] = []
                output[dirpath] = self.checkvc(dirpath, 'svn')
            if '.git' in subdirs:
                # here, it is not necessary, but we do it anyway to reduce search time
                # note that this will cause repos to be ignored if they are sub-repos of git repos
                subdirs[:] = []
                output[dirpath] = self.checkvc(dirpath, 'git')

            if self.depth is not None:
                # Strip off the root directory to get depth of the current subdirectory.
                dir_depth = len(dirpath[absrootlen:].split(os.sep))
                if dir_depth > self.depth:
                    subdirs[:] = []

            # we are not interested in hidden directories.
            subdirs[:] = [x for x in subdirs if not x.startswith('.')]
        return output

    def checkvc(self, path, type, try_update = True):
        self.logger.info("Checking repository: %s", path)
        if type == 'git':
            (status, files) = self._git_get_status(path)
        else:
            (status, files) = self._svn_get_status(path)

        if status == None:
            self.logger.warning("Could not check this repository: %s" % path)
            self.logger.error(files)
            if self.interactive_add_ignore:
                print("What to do now? [n]o action for now, always skip this [r]epository, [q]uit, use [s]hell to investigate/fix")
                key = read_single_keypress()
                if key == 'r':
                    print("Will skip repository in future runs.")
                    self.skip_repositories.append(path)
                elif key == 'q':
                    self.shutdown()
                    sys.exit("Good bye.")
                elif key == 's':
                    subprocess.call([self.shell], cwd=path)
                    return self.checkvc(path, type, try_update)
                else:
                    print("No action.")
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

        if 'added' in status and self.interactive_add_ignore:
            if type == 'git':
                repeat = self._git_add_ignore(path, files['added'])
                if repeat:
                    return self.checkvc(path, type)

        if 'needs-pull' in status and try_update and self.auto_update:
            self.logger.info("Updating repository: %s", path)
            if type == 'git':
                self._git_update(path)
            else:
                self._svn_update(path)
                return self.checkvc(path, type, False)

        if ('added' in status or 'needs-pull' in status or 'modified' in status or 'needs-push' in status) and self.launch_shell:
            print("Launch a shell to investigate/fix this? [y]es [n]o [q]uit")
            key = read_single_keypress()
            if key == 'y' or key == 'Y':
                subprocess.call([self.shell], cwd=path)
                return self.checkvc(path, type, try_update)
            elif key == 'q':
                self.shutdown()
                sys.exit("Good bye.")


        return status

    def _git_get_status(self, path):
        out_status = []
        out_files = {
            'modified': [],
            'added': []
        }

        try:
            subprocess.check_output(["git", "-C", path, "remote", "update"], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(e.output)
            return (None, e.output)

        # Use the strategy described in https://stackoverflow.com/questions/3258243/git-check-if-pull-needed to check if a pull is needed
        try:
            local = subprocess.check_output(["git", "-C", path, "rev-parse", "@"], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(e.output)
            return (None, e.output)

        try:
            remote = subprocess.check_output(["git", "-C", path, "rev-parse", "@{u}"], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(e.output)
            return (None, e.output)

        try:
            base = subprocess.check_output(["git", "-C", path, "merge-base", "@", "@{u}"], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
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
            status = subprocess.check_output(["git", "-C", path, "status", "--porcelain"], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(e.output)
            return (None, e.output)

        for line in status.split("\n")[:-1]:
            self.logger.debug("Checking: >>%s<<" % line)
            file = os.path.join(path, line[3:])
            if file in self.noaction_files or file in self.skip_files:
                continue
            if line[1] in 'MARCD':
                if not 'modified' in out_status:
                    out_status.append("modified")
                out_files['modified'].append(file)
            if line[0:2] == '??' and not self.ignore_added:
                if not 'added' in out_status:
                    out_status.append("added")
                out_files['added'].append(file)

        return (out_status, out_files)

    def _git_update(self, path):
        try:
            subprocess.check_output(["git", "-C", path, "pull"], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(e.output)

    # return True to indicate that the repo should be re-read
    def _git_add_ignore(self, path, files):
        print("GIT Repository %s" % path)
        for f in files:
            if f in self.noaction_files or f in self.skip_files:
                continue
            print("New file: %s" % f)
            print("  [a]dd to repo\n  add to git[i]gnore\n  add to [g]lobal gitignore\n  [n]o action\n  no action on [w]hole repostory\n  always s[k]ip this file\n  always skip this [r]epository\n  use [s]hell to investigate/fix\n  [q]uit")
            key = read_single_keypress()
            if key == 'a':
                print("Adding file to repository.")
                try:
                    subprocess.check_output(["git", "-C", path, "add", f], stderr=subprocess.STDOUT, text=True)
                except subprocess.CalledProcessError as e:
                    self.logger.error(e.output)
            elif key == 'i':
                proposal = self._git_prepare_ignore(path, f)
                ignore = input("What exactly to add to .gitignore? [%s] " % proposal).strip()
                if ignore == "":
                    ignore = proposal
                self._git_add_to_ignore_file(path, ignore, False)
                return True
            elif key == 'g':
                print("Note: Using/creating a global gitignore file at ~/.gitignore")
                proposal = self._git_prepare_ignore(path, f)
                ignore = input("What exactly to add to global gitignore? [%s] " % proposal).strip()
                if ignore == "":
                    ignore = proposal
                self._git_add_to_ignore_file(path, ignore, True)
                return True
            elif key == 'k':
                self.skip_files.append(f)
                print("Will skip file in future runs.")
            elif key == 'r':
                self.skip_repositories.append(path)
                print("Will skip repository in future runs.")
                return False
            elif key == 's':
                subprocess.call([self.shell], cwd=path)
                return True
            elif key == 'w':
                print("Skipping repository.")
                return False
            elif key == 'q':
                self.shutdown()
                sys.exit("Good bye.")
            else:
                print("Doing nothing...")
                self.noaction_files.append(f)
        return False

    def _git_prepare_ignore(self, path, what):
        if what.startswith(path):
            what = what[len(path):]
        if what.startswith("#"):
            what = "\\%s" % what
            print("(added backslash, it's a .gitignore rule for files that start with #)")
        return what

    def _git_add_to_ignore_file(self, path, what, globally):
        if globally:
            ignorefile = os.path.expanduser("~/.gitignore")
        else:
            ignorefile = os.path.join(path, ".gitignore")

        created = False
        if os.path.exists(ignorefile):
            gitignore = open(ignorefile, 'r').read()
        else:
            gitignore = "# Fresh git ignore file created by vcwalker. Feel free to change as needed."
            created = True

        gitignore = "%s\n%s" % (gitignore, what)
        open(ignorefile, 'w').write(gitignore)
        print("Added ignore file entry.")
        if globally:
            try:
                subprocess.check_output(["git", "config", "--global", "core.excludesfile", ignorefile], stderr=subprocess.STDOUT, text=True)
            except subprocess.CalledProcessError as e:
                self.logger.error(e.output)

    def _svn_get_status(self, path):
        out_status = []
        out_files = {
            'modified': [],
            'added': []
        }
        try:
            status = subprocess.check_output(["svn", "status", "-u", path], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
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
            status = subprocess.check_output(["svn", "upgrade", path], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            return False
        return True

    def _svn_update(self, path):
        try:
            status = subprocess.check_output(["svn", "update", path], stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(e.output)

    def print_summary(self, result):
        print("# <-- remote changes; --> local changes; |--| diverged; M modified files; A added files; E error.")
        for path, result in list(result.items()):
            if result == []:
                continue
            if result == None:
                a, b, c, d = " ", "E", "E", " "
            else:
                a = "|" if "diverged" in result else ("<" if "needs-pull" in result else " ")
                b = "M" if "modified" in result else "-"
                c = "A" if "added" in result else "-"
                d = "|" if "diverged" in result else (">" if "needs-push" in result else " ")

            print(" %s%s%s%s  %s" % (a, b, c, d, path))

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description = "Recursively find GIT and SVN repositories in a given path and check if remote or local files need updates.")
    parser.add_argument('--update', '-u', dest="auto_update", action="store_true", help="Perform a git pull or svn update if a repository is found to be outdated.")
    parser.add_argument('--upgrade', dest="auto_upgrade", action="store_true", help="Perform a svn upgrade if necessary (outdated SVN data format version in repository).")
    parser.add_argument('--ignore-added', '-n', dest="ignore_added", action="store_true", help="Ignore files added in the local file system.")
    parser.add_argument('--verbose', '-v', dest="verbose", default=0, action="count", help="Output all messages about single repositories. Use twice for debug output.")
    parser.add_argument('--no-color', dest="no_color", action="store_true", help="Use no color in logging output.")
    parser.add_argument('--no-summary', dest="summary", action="store_false", help="Don't summarize the results.")
    parser.add_argument('--interactive', '-i', dest="interactive", action="store_true", help="Ask for adding/ignoring new files.")
    parser.add_argument('--depth', '-d', dest="depth", default=None, type=int, help="Maximum directory depth.")
    parser.add_argument('--shell', '-s', dest="shell", action="store_true", help="Launch a shell in every directory that has modified/added files (implies -v).")
    parser.add_argument('--settings-file', '-f', dest="settingsfile", default="~/.config/vcwalker", help="An alternate settings file (default: ~/.config/vcwalker).")
    parser.add_argument('path', nargs="*", default=["."], help="Paths to search for repositories (Default: Working Directory).")
    args = parser.parse_args()

    if not args.no_color:
        logging.setLoggerClass(ColoredLogger)

    if args.shell:
        args.verbose = max(args.verbose, 1)

    logging.getLogger('walker').setLevel({
        0: logging.WARN,
        1: logging.INFO,
        2: logging.DEBUG
    }[args.verbose])

    if args.depth is not None and args.depth < 0:
        print("Error: depth cannot be negative")
        exit(1)

    walker = VCWalker(args.auto_update, args.auto_upgrade, args.ignore_added, args.interactive, os.path.expanduser(args.settingsfile), args.shell, args.depth)

    result = {}
    for d in args.path:
        result.update(walker.walkdir(d))

    if args.summary:
        walker.print_summary(result)
    walker.shutdown()
