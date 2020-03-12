#!/usr/bin/env python
#
# Wrapper script for Java Conda packages that ensures that the java runtime
# is invoked with the right options. Adapted from the bash script (http://stackoverflow.com/questions/59895/can-a-bash-script-tell-what-directory-its-stored-in/246128#246128).

#
# Program Parameters
#
import os
import requests
import subprocess
import sys
import time
import zipfile
from os import access
from os import getenv
from os import X_OK
from pathlib import Path
from tqdm import tqdm

jar_file = 'MPA-3.3.jar'
data_dump_url = "https://zenodo.org/api/files/cd550e2e-151b-4650-9369-feb30f88f525/mpa_ressources_incl_swissprot_03-2020.zip"

default_jvm_mem_opts = ['-Xms2g', '-Xmx4g']


# !!! End of parameter section. No user-serviceable code below this line !!!


def printerr(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def real_dirname(path):
    """Return the symlink-resolved, canonicalized directory-portion of path."""
    return os.path.dirname(os.path.realpath(path))


def java_executable():
    """Return the executable name of the Java interpreter."""
    java_home = getenv('JAVA_HOME')
    java_bin = os.path.join('bin', 'java')

    if java_home and access(os.path.join(java_home, java_bin), X_OK):
        return os.path.join(java_home, java_bin)
    else:
        return 'java'


def jvm_opts(argv):
    """Construct list of Java arguments based on our argument list.

    The argument list passed in argv must not include the script name.
    The return value is a 3-tuple lists of strings of the form:
      (memory_options, prop_options, passthrough_options)
    """
    mem_opts = []
    prop_opts = []
    pass_args = []

    for arg in argv:
        if arg.startswith('-D'):
            prop_opts.append(arg)
        elif arg.startswith('-XX'):
            prop_opts.append(arg)
        elif arg.startswith('-Xm'):
            mem_opts.append(arg)
        else:
            pass_args.append(arg)

    # In the original shell script the test coded below read:
    #   if [ "$jvm_mem_opts" == "" ] && [ -z ${_JAVA_OPTIONS+x} ]
    # To reproduce the behaviour of the above shell code fragment
    # it is important to explictly check for equality with None
    # in the second condition, so a null envar value counts as True!

    if mem_opts == [] and getenv('_JAVA_OPTIONS') is None:
        mem_opts = default_jvm_mem_opts

    return (mem_opts, prop_opts, pass_args)


def read_config(config_file):
    cfg = {}
    with open(config_file, "r") as f:
        for l in f.readlines():
            l_stripped = l.strip()
            if l_stripped.startswith("#"):
                continue
            elif l_stripped == "":
                continue
            else:
                split_vals = l_stripped.split("=")
                if len(split_vals) != 2:
                    printerr(f"Got unexpected line in config file '{config_file}'")
                    printerr(l)
                    sys.exit(1)
                cfg[split_vals[0]] = split_vals[1]
    return cfg


def set_cfg_values(dict_of_vals_to_change, config_file):
    out_lines = []
    with open(config_file, "r") as f:
        for l in f.readlines():
            l_stripped = l.strip()
            if l_stripped.startswith("#"):
                pass
            elif l_stripped == "":
                pass
            else:
                split_vals = l_stripped.split("=")
                if len(split_vals) != 2:
                    printerr(f"Got unexpected line in config file '{config_file}'")
                    printerr(l)
                    sys.exit(1)
                else:
                    key, value = split_vals
                    if key in dict_of_vals_to_change:
                        l = f"{key}={dict_of_vals_to_change[key]}\n"
                        del dict_of_vals_to_change[key]
            out_lines.append(l)
    if dict_of_vals_to_change:
        if not l.endswith("\n"):
            out_lines.append("\n")
        out_lines.extend([f"{k}={v}\n" for k, v in dict_of_vals_to_change.items()])
    with open(config_file, "w") as f:
        f.writelines(out_lines)


def is_first_run(config):
    if ("first_run" not in config) or (config["first_run"] == "True"):
        return True
    return False


class SqlServerWrapper:
    def __init__(self, datadir):
        self.datadir = datadir

    def __enter__(self):
        args = ["mysqld", "--datadir", self.datadir]
        printerr("Starting MySQL-Server: '", " ".join(args), "'", sep='')
        self.daemon = subprocess.Popen(args)

    def __exit__(self, type, value, traceback):
        # send term signal to mysqld
        printerr("Shutting down MySQL-Server... ", end='')
        self.daemon.terminate()
        self.daemon.communicate()
        printerr("Done!")


def download_file(url):
    file_name = url.split('/')[-1]
    file_name_part = file_name + ".prt"
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        file_size_mbyte = int(float(response.headers['Content-Length']) / 1024 / 1024)

        printerr(f"Downloading: {file_name}, size: {file_size_mbyte} MB")
        pbar = tqdm(total=file_size_mbyte, position=0, leave=True, unit="MB")
        with open(file_name_part, 'wb') as handle:
            for chunk in response.iter_content():
                if chunk:  # filter out keep-alive new chunks
                    handle.write(chunk)
                    chunk_size_mb = len(chunk) / 1024 / 1024
                    pbar.update(chunk_size_mb)
    os.rename(file_name_part, file_name)
    return os.path.abspath(file_name)


def extract_and_overwrite(zip_file, target_dir):
    printerr("Extracting to:", target_dir)
    with zipfile.ZipFile(zip_file, "r") as zip_handle:
        zip_handle.extractall(path=target_dir)


def load_preprocessed_data(cfg, url):
    fasta_subdir = cfg["path.fasta"][1:] if cfg["path.fasta"].startswith("/") else cfg["path.fasta"]
    fasta_dir = os.path.join(cfg["base_path"], fasta_subdir)
    zip_file = download_file(url)

    extract_and_overwrite(zip_file=zip_file, target_dir=fasta_dir)
    os.remove(zip_file)
    sql_dump = os.path.join(fasta_dir, "metaprot_swissprot_mar2020.sql")
    return sql_dump


def prompt_user_for_data_download():
    while True:
        user_input = input("Download preprocessed FASTA Database (~1 GB)? [Y/n] ").lower()
        if user_input not in ["", "y", "n"]:
            print("Valid options are: y, n")
        else:
            if user_input in ["", "y"]:
                wants_db = True
            else:
                wants_db = False
            break
    return wants_db


def get_abs_sql_data_path(cfg):
    mpa_data_base_path = cfg["base_path"]
    sql_data_rel_path = cfg["sqlDataDir"]
    sql_data_path = os.path.join(mpa_data_base_path, sql_data_rel_path)
    return sql_data_path


def create_empty_dirs(cfg, jar_dir):
    dir_cfg_keys = ["path.transfer",
                    "path.fasta",
                    "path.xtandem.output",
                    "path.omssa.output"]

    data_base_path = get_data_base_path(cfg, jar_dir)
    dirs = []
    for k in dir_cfg_keys:
        dir_string = cfg[k]
        subdir = dir_string[1:] if dir_string.startswith("/") else dir_string
        abs_dir = os.path.join(data_base_path, subdir)
        dirs.append(abs_dir)
        if k == "path.fasta":
            dirs.append(os.path.join(abs_dir, "Pep"))

    if not all(map(os.path.isdir, dirs)):
        printerr("Creating empty directories:")
    for d in dirs:
        if not os.path.isdir(d):
            printerr(f"\t{d}")
            Path(d).mkdir(parents=True)


def init_sql_db(cfg):
    mpa_data_base_path = cfg["base_path"]
    sql_data_path = get_abs_sql_data_path(cfg)
    # initialize sql db
    # init sql data dir
    subprocess.call(["mysqld", "--initialize-insecure", "--datadir", sql_data_path])
    # wants_db = prompt_user_for_data_download()
    wants_db = False  # False, since data_dump_url is not live yet
    if wants_db:
        sql_dump = load_preprocessed_data(cfg, url=data_dump_url)
    else:
        sql_dump = os.path.join(mpa_data_base_path, "init/mysql_minimal_incl_taxonomy.sql")
    with SqlServerWrapper(sql_data_path):
        time.sleep(3.)
        cmd = "mysql -u root --execute='create database mpa_server;'"
        printerr(f"Creating database: {cmd}")
        subprocess.call(cmd, shell=True)
        cmd = f"mysql -u root --database='mpa_server' < {sql_dump}"
        printerr("loading sql dump:", sql_dump)
        printerr(f"MySQL command: {cmd}")
        exit_code = subprocess.call(cmd, shell=True)
    if not exit_code == 0:
        printerr("Loading of sql dump was not successful, exiting")
        sys.exit(1)
    os.remove(sql_dump)


def get_data_base_path(cfg, jar_dir):
    mpa_data_base_path = cfg["base_path"]
    if not os.path.isabs(mpa_data_base_path):
        mpa_data_base_path = os.path.join(os.path.abspath(jar_dir), mpa_data_base_path)
    return mpa_data_base_path


def make_data_base_path_in_cfg_absolute(cfg, config_file, jar_dir):
    abs_data_path = get_data_base_path(cfg, jar_dir)
    cfg_data_path = cfg["base_path"]
    if abs_data_path != cfg_data_path:
        set_cfg_values({"base_path": abs_data_path}, config_file)
        cfg = read_config(config_file)
    return cfg


def main():
    java = java_executable()
    """
    mpa-server updates files relative to the path of the jar file.
    """
    (mem_opts, prop_opts, pass_args) = jvm_opts(sys.argv[1:])
    jar_dir = real_dirname(sys.argv[0])

    if pass_args != [] and pass_args[0].startswith('eu'):
        jar_arg = '-cp'
    else:
        jar_arg = '-jar'

    jar_path = os.path.join(jar_dir, jar_file)

    java_args = [java] + mem_opts + prop_opts + [jar_arg] + [jar_path] + pass_args

    config_file = os.path.join(jar_dir, "config_LINUX.properties")
    cfg = read_config(config_file)
    if is_first_run(cfg):
        cfg = make_data_base_path_in_cfg_absolute(cfg, config_file, jar_dir)
        create_empty_dirs(cfg, jar_dir)
        init_sql_db(cfg)

        set_cfg_values({"first_run": False}, config_file)

    sql_data_abs_path = get_abs_sql_data_path(cfg)

    with SqlServerWrapper(sql_data_abs_path):
        java_exit_code = subprocess.call(java_args, cwd=jar_dir)

    sys.exit(java_exit_code)


if __name__ == '__main__':
    main()
