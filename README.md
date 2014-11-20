VCWalker
========

VCWalker recursively checks SVN or GIT repositories for remote and local changes.

By default, VCWalker shows whether remote changes, local (committed) changes, and locally modified or added files are present.

    usage: vcwalker.py [-h] [--update] [--upgrade] [--ignore-added] [--verbose]
                       [--no-color] [--no-list] [--interactive] [--shell]
                       [--settings-file SETTINGSFILE]
                       [path [path ...]]
    
    Recursively find GIT and SVN repositories in a given path and check if remote
    or local files need updates.

    positional arguments:
      path                  Paths to search for repositories (Default: Working
                            Directory).

	optional arguments:
	 -h, --help            show this help message and exit
	 --update, -u          Perform a git pull or svn update if a repository is
						   found to be outdated.
	 --upgrade             Perform a svn upgrade if necessary (outdated SVN data
						   format version in repository).
	 --ignore-added, -n    Ignore files added in the local file system.
	 --verbose, -v         Output all messages about single repositories. Use
						   twice for debug output.
	 --no-color            Use no color in logging output.
	 --no-list             Don't summarize the results.
	 --interactive, -i     Ask for adding/ignoring new files.
	 --shell, -s           Launch a shell in every directory that has
						   modified/added files (implies -v).
	 --settings-file SETTINGSFILE, -f SETTINGSFILE
						   An alternate settings file (default:
						   ~/.config/vcwalker).

VCWalker is *BETA*. Use at your own risk.
