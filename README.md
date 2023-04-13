# timelog

CLI tool to binary search in a large log file.

## Problem

Our log files are large and growing very quickly. When you receive a notification about an incident, you usually know the time, but how can you retrieve the relevant log lines for that particular time?

The typical approach is to use the `grep` command on the log file with a pattern that allows you to select the appropriate log lines for the desired time. However, a major disadvantage of this method is that `grep` has to read the entire file to perform its task. When you have over **100 GB** of log files, using `grep` can significantly waste your time.

If the incident happened recently, you can speed up the process by piping the input of `grep` from `tail -n 1000000 <logfile>` command, which selects the last million lines from the log file. However, every time you have to estimate how many millions of lines will be enough to contain the log lines you need. Moreover, `tail` for 10 million lines can still take a significant amount of time. And even with this method, you may still select the wrong number of lines and not retrieve the required log lines.

## Solution

Our log files are sorted since they represent events in chronological order. Therefore, we can use a [binary search](https://en.wikipedia.org/wiki/Binary_search_algorithm) to find specific lines with a particular time in a large file significantly faster than by reading the entire file.

Thus, I have written a script to perform this task efficiently. Essentially, it searches for the file offset of the line with the specified time and then prints the file to stdout from that offset or opens a `less` pager program with the file at the line with the specified time. The script can find the appropriate offset almost instantly, regardless of the size of the log file.

## Help and usage

```
$ ./timelog.py -h
usage: timelog.py [-h] [-l] [-t TIME_TO] [-v] [-d] [-a ARG] [-n] [-c CHUNKSIZE]
                  filename time_from

Perform a binary search for the specified time in a big text log file.
Print found log lines to stdout by executing `dd` with proper args,
or view it with `less` with proper position on found time.

positional arguments:
  filename              Path to the log file
  time_from             Time string to search the first line in log file. Can be in one of
                        the following formats: `YYYY/mm/dd HH:MM:SS:sss` (full), `YYYY/mm/dd
                        HH:MM:SS`, `YYYY/mm/dd HH:MM` (short), `YY/mm/dd` (date only),
                        `HH:MM:SS:sss`, `HH:MM:SS`, or `HH:MM` (time only, date from the
                        first line of file)

options:
  -h, --help            show this help message and exit
  -l, --less            Use `less` program to view the file instead of printing it with `dd`.
                        Conflicts with --time-to option (default: False)
  -t TIME_TO, --time-to TIME_TO
                        Set the last time string to output from in log file, NOT INCLUSIVE.
                        Conflicts with --less option. The same format as for time_from
                        (default: None)
  -v, --verbose         Show debug info on stderr (default: False)
  -d, --debug           Debug binary search stages to stderr (default: False)
  -a ARG, --arg ARG     Add an extra argument to the resulting command line (default: None)
  -n, --noexec          Do not execute resulting command, just print it to stdout (default:
                        False)
  -c CHUNKSIZE, --chunksize CHUNKSIZE
                        Max chunk size for linear search in file (default: 81920)

Examples of the resulting commands:

    dd status=none if=bigfile.log iflag=skip_bytes skip=2488818942
    dd status=none if=bigfile.log iflag=skip_bytes,count_bytes skip=2488818942 count=451258
    less -n +2488818942P bigfile.log
```
