import json
import os
import rpmfile
import subprocess
import time
import urllib.request

from binaryaudit import abicheck
from binaryaudit import run
from binaryaudit import util


def process_downloads(source_dir, new_json_file, old_json_file, output_dir,
                      build_id, product_id, db_conn, remaining_files, all_suppressions):
    ''' Finds and downloads older versions of RPMs.

        Parameters:
            source_dir (str): The path to the input directory of RPMs
            new_json_file (str): The name of the JSON file containing the newer set of packages after so based filtering
            old_json_file (str): The name of the JSON file containing the older set of packages
            output_dir (str): The path to the output directory of abipkgdiff
            build_id (str): The build id
            product_id (str): The product id
            db_conn: The db connection
            remianing_files (int): The number of files left after filtering
        Returns:
            overall_status (str): Returns "fail" if an incompatibility is found in at least 1 RPM, otherwise returns "pass"
    '''
    processed_files = 0
    overall_status = "PASSED"
    conf_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "conf"))
    # TODO: move old dir to tmpdir for mariner
    if not os.path.exists(os.path.join(source_dir, "old")):
        os.mkdir(os.path.join(source_dir, "old"))
    old_rpm_dict = {}
    with open(new_json_file, "r") as file:
        data = json.load(file)
    for key, values in data.items():
        processed_files += len(data[key])
        for value in values:
            with rpmfile.open(os.path.join(source_dir, value)) as rpm:
                name = rpm.headers.get("name")
            old_rpm_name = download(key, source_dir, name, old_rpm_dict)
        if old_rpm_name == "":
            util.note("Processed {} of {} files".format(processed_files, remaining_files))
            continue
        with open(old_json_file, "w") as outputFile:
            json.dump(old_rpm_dict, outputFile, indent=2)
        ret_status = generate_abidiffs(key, source_dir, new_json_file, old_json_file, output_dir,
                                       conf_dir, build_id, product_id, db_conn, all_suppressions)
        util.note("Status: {}".format(ret_status))
        if ret_status != 0:
            overall_status = "FAILED"
        util.note("Processed {} of {} files".format(processed_files, remaining_files))
    return overall_status


def download(key, source_dir, name, old_rpm_dict):
    ''' Finds and downloads older versions of RPMs.

        Parameters:
            key (str): The source name for the group of RPMs
            source_dir (str): The path to the input directory of RPMs
            name: The name of the RPM
            old_rpm_dict: The dictionary containing the older set of packages
    '''
    docker, docker_exit_code = run.run_command_docker(["/usr/bin/dnf", "repoquery", "--quiet", "--latest-limit=1", name],
                                                      None, subprocess.PIPE)
    old_rpm_name = docker.stdout.read().decode('utf-8')
    if old_rpm_name == "":
        return old_rpm_name
    old_rpm_name = old_rpm_name.rstrip("\n")
    for i in range(3):
        docker_loc, docker_loc_exit_code = run.run_command_docker(["/usr/bin/dnf", "repoquery", "--quiet", "--location",
                                                                  "--latest-limit=1", name], None, subprocess.PIPE)
        url = docker_loc.stdout.read().decode('utf-8')
        if url != "":
            break
    url = url.rstrip("\n")
    util.debug("url: {}".format(url))
    if i == 2:
        return ""
    for j in range(3):
        try:
            urllib.request.urlretrieve(url, source_dir + "old/" + old_rpm_name)
            break
        except Exception:
            pass
    if j == 2:
        return ""
    old_rpm_dict.setdefault(key, []).append(old_rpm_name)
    return old_rpm_name


def generate_abidiffs(key, source_dir, new_json_file, old_json_file, output_dir,
                      conf_dir, build_id, product_id, db_conn, all_suppressions):
    ''' Runs abipkgdiff against the grouped packages.

        Parameters:
            key (str): The source name for the group of RPMs
            source_dir (str): The path to the input directory of RPMs
            new_json_file (str): The name of the JSON file containing the newer set of packages
            old_json_file (str): The name of the JSON file containing the older set of packages
            output_dir (str): The path to the output directory of abipkgdiff
            conf_dir (str): The absolute path to the conf directory
            build_id (str): The build id
            product_id (str): The product id
            db_conn: The db connection
            all_suppressions (list): a list of the filepaths to suppression files used

        Returns:
            abipkgdiff_exit_code (int): Returns non-zero if an incompatibility found
    '''
    # new_... handles the newer set of packages
    # old_... handles the older set of packages
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    with open(new_json_file, "r") as new_file:
        new_data = json.load(new_file)
    with open(old_json_file, "r") as old_file:
        old_data = json.load(old_file)
    rpms_with_so, cmd_supporting_args = sortRPMs(key, source_dir, new_data, old_data)
    i = 0
    for rpm in rpms_with_so:
        if i % 2 == 0:
            command_list = ["abipkgdiff"]
            for suppr in all_suppressions:
                command_list += ["--suppr", suppr]
            old_main_rpm = rpm
        i += 1
        command_list.append(rpm)
        if i % 2 == 1:
            continue
        new_main_rpm = rpm
        for arg in cmd_supporting_args:
            command_list.append(arg)
        with open("output_file", "w") as output_file:
            start_time = time.monotonic()
            abipkgdiff, abipkgdiff_exit_code = run.run_command(command_list, None, output_file)
            end_time = time.monotonic()
            exec_time = (end_time-start_time)*1000000
            with rpmfile.open(old_main_rpm) as rpm:
                name = rpm.headers.get('name').decode('utf-8')
                old_version = rpm.headers.get('version').decode('utf-8')
                old_release = rpm.headers.get('release').decode('utf-8')
            with rpmfile.open(new_main_rpm) as rpm:
                new_version = rpm.headers.get('version').decode('utf-8')
                new_release = rpm.headers.get('release').decode('utf-8')
            old_VR = old_version + "-" + old_release
            new_VR = new_version + "-" + new_release
            out = ""
            if abipkgdiff_exit_code != 0:
                util.note("Incompatibility found between {} - {} and {} - {}".format(name, old_VR, name, new_VR))
                fileName = util.build_diff_filename(name, old_VR, new_VR)
                outFilePath = os.path.join(output_dir, fileName)
                os.rename("output_file", outFilePath)
                with open(outFilePath) as f:
                    out = f.read()
        status = abicheck.diff_get_bit(abipkgdiff_exit_code)
        insert_db(db_conn, build_id, product_id, name, old_VR, new_VR, exec_time, status, out)
    return abipkgdiff_exit_code


def sortRPMs(key, source_dir, new_data, old_data):
    ''' Sorts the RPMs depnding on whether or not they have
        "debuginfo" or "devel" in their name.

        Parameters:
            key (str): The source name for the group of RPMs
            source_dir (str): The path to the input directory of RPMs
            new_data (dict): The dictionary containing the newer set of packages
            old_data (dict): The dictionary containing the older set of packages

    Returns:
            rpms_with_so (list): The list of RPMs not containing "debuginfo" or "devel" in their name
            cmd_supporting_args (list): The list of RPMs containing "debuginfo" or "devel" in their name
    '''
    rpms_with_so = []
    cmd_supporting_args = []
    count = -1
    for value in old_data[key]:
        count += 1
        if "-debuginfo-" in value:
            cmd_supporting_args.append("--d1")
            cmd_supporting_args.append(source_dir + "old/" + value)
            cmd_supporting_args.append("--d2")
            cmd_supporting_args.append(source_dir + new_data[key][count])
        elif "-devel-" in value:
            cmd_supporting_args.append("--devel1")
            cmd_supporting_args.append(source_dir + "old/" + value)
            cmd_supporting_args.append("--devel2")
            cmd_supporting_args.append(source_dir + new_data[key][count])
        else:
            rpms_with_so.append(source_dir + "old/" + value)
            rpms_with_so.append(source_dir + new_data[key][count])
    return rpms_with_so, cmd_supporting_args


def insert_db(db_conn, build_id, product_id, name, old_VR, new_VR, exec_time, status, out):
    ''' Inserts data into the database

        Parameters:
            db_conn: The db connection
            build_id (str): The build id
            product_id (str): The product id
            name (str): The name of the RPM
            old_VR (str): The version and release of the older RPM
            new_VR (str): The version and release of the newer RPM
            exec_time (int): The execution time of abipkgdiff in microseconds
            status (str): The status output of abipkgdiff
            out (str): The output of abipkgdiff
    '''
    try:
        if db_conn.is_db_connected:
            db_conn.insert_ba_transaction_details(build_id, product_id, name, old_VR, new_VR, exec_time, status, out)
            util.debug("Inserted into database: {}".format(name))
        else:
            util.debug("Not connected")
    except Exception:
        pass
