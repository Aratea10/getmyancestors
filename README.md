getmyancestors
==============

_getmyancestors_ is a python3 package that downloads family trees in GEDCOM format from FamilySearch.

This program is now in production phase, but bugs might still be present. Features will be added on request. It is provided as is.

The project is maintained at https://github.com/Linekio/getmyancestors. Visit here for the latest version and more information.

This script requires python3 and the modules indicated in the requirements.txt file. To install the modules, run in your terminal:


Installation
============

The easiest way to install _getmyancestors_ is to use pip:

`pip install getmyancestors`

Otherwise, you can download the source package and then execute in the folder:

`pip install .`

How to use
==========

With graphical user interface:

```
fstogedcom
```

Command line examples:

Download four generations of ancestors for the main individual in your tree and output gedcom on stdout (will prompt for username and password):

```
getmyancestors
```

Download four generations of ancestors and output gedcom to a file while generating a verbode stderr (will prompt for username and password):

```
getmyancestors -o out.ged -v
```

Download four generations of ancestors for individual LF7T-Y4C and generate a verbose log file:

```
getmyancestors -u username -p password -i LF7T-Y4C -o out.ged -l out.log -v
```

Download six generations of ancestors for individual LF7T-Y4C and generate a verbose log file:

```
getmyancestors -a 6 -u username -p password -i LF7T-Y4C -o out.ged -l out.log -v
```

Download four generations of ancestors for individual LF7T-Y4C including all their children and their children spouses:

```
getmyancestors -d 1 -m -u username -p password -i LF7T-Y4C -o out.ged
```

Download six generations of ancestors for individuals L4S5-9X4 and LHWG-18F including all their children, grandchildren and their spouses:

```
getmyancestors -a 6 -d 2 -m -u username -p password -i L4S5-9X4 LHWG-18F -o out.ged
```

Download four generations of ancestors for individual LF7T-Y4C including LDS ordinances (need LDS account)

```
getmyancestors -c -u username -p password -i LF7T-Y4C -o out.ged
```

Merge two Gedcom files

```
mergemyancestors -i file1.ged file2.ged -o out.ged
```



All connected relatives (experimental)
======================================

This additional command explores all available FamilySearch relationships in
every direction: parents, children, spouses, the parents of spouses, their
children and so on. It does not require a generation count and does not assume
that the tree ends at a given ancestor.

Unlike `getmyancestors -a ... -d ... -m`, this command repeatedly visits the
relatives of each new person it discovers. FamilySearch may connect a huge
number of people, and some records may be inaccessible or unavailable. It
cannot guarantee that every person in FamilySearch will be reachable.

Install this development branch in an isolated environment, for example with
`uvx --python 3.12 --from "git+https://github.com/Aratea10/getmyancestors.git@feat/complete-family-traversal" getmyancestors-all`.

Example:

```sh
getmyancestors-all -i LVXP-TH5 -o ~/Downloads/familysearch_extendido.ged
```

The default is to **pause after 1,000 people** as a safety precaution. To keep
exploring, run the same command again with `--max-people 5000`, or use
`--max-people 0` to run without a person cap (which could be enormous).
These are limits on downloaded people, **not** generations.

An SQLite checkpoint is automatically stored next to the GEDCOM using the
same name and `.sqlite` extension. Every successful person response is saved;
the tool resumes from that file on a later run and creates a GEDCOM snapshot
from the people retrieved so far. If stopped with Ctrl+C, it attempts to
export the current snapshot. The checkpoint is private family-history data:
keep it safe and do not commit it to Git.

Use the **same output path** on subsequent runs to reuse the checkpoint.
The user name and password are requested interactively and are not stored in
the checkpoint. Requests are rate-limited by default to two per second.
This is an experimental feature; verify the resulting GEDCOM before using it
as the only copy of your research.


Support
=======

Submit questions or suggestions, or feature requests by opening an Issue at https://github.com/Linekio/getmyancestors/issues

Donation
========

If this project help you, you can give me a tip :)

[![paypal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=98X3CY93XTAYJ)
