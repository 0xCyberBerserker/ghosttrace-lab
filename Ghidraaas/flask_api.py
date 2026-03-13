#!/usr/bin/env python3
# -*- coding: utf-8 -*-

##############################################################################
#                                                                            #
#  GhIDA: Ghidraaas - Ghidra as a Service                                    #
#                                                                            #
#  Copyright 2019 Andrea Marcelli and Mariano Graziano, Cisco Talos          #
#                                                                            #
#  Licensed under the Apache License, Version 2.0 (the "License");           #
#  you may not use this file except in compliance with the License.          #
#  You may obtain a copy of the License at                                   #
#                                                                            #
#      http://www.apache.org/licenses/LICENSE-2.0                            #
#                                                                            #
#  Unless required by applicable law or agreed to in writing, software       #
#  distributed under the License is distributed on an "AS IS" BASIS,         #
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  #
#  See the License for the specific language governing permissions and       #
#  limitations under the License.                                            #
#                                                                            #
##############################################################################

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import traceback
import glob

from flask import Flask
from flask import request

from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import RequestEntityTooLarge

import coloredlogs
import logging
log = None

app = Flask(__name__)
DEFAULT_MAX_CONTENT_LENGTH_MB = 1024

# Load configuration
with open("config/config.json") as f_in:
    j = json.load(f_in)
    SAMPLES_DIR = j['SAMPLES_DIR']
    IDA_SAMPLES_DIR = j['IDA_SAMPLES_DIR']
    GHIDRA_SCRIPT = j['GHIDRA_SCRIPT']
    GHIDRA_OUTPUT = j['GHIDRA_OUTPUT']
    GHIDRA_PROJECT = j['GHIDRA_PROJECT']
    GHIDRA_PATH = j['GHIDRA_PATH']
    GHIDRA_HEADLESS = os.path.join(GHIDRA_PATH, "support/analyzeHeadless")
    DEFAULT_JAVA_HOME = os.environ.get("JAVA_HOME", "/opt/java/openjdk")


#############################################
#       UTILS                               #
#############################################

def set_logger(debug):
    """
    Set logger level and syntax
    """
    global log
    log = logging.getLogger('ghidraaas')
    if debug:
        loglevel = 'DEBUG'
    else:
        loglevel = 'INFO'
    coloredlogs.install(fmt='%(asctime)s %(levelname)s:: %(message)s',
                        datefmt='%H:%M:%S', level=loglevel, logger=log)


def sha256_hash(stream):
    """
    Compute the sha256 of the stream in input
    """
    stream.seek(0)
    sha256_hash = hashlib.sha256()
    # Read and update hash string value in blocks of 4K
    for byte_block in iter(lambda: stream.read(4096), b""):
        sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def server_init():
    """
    Server initialization: flask configuration, logging, etc.
    """
    # Check if SAMPLES_DIR folder is available
    if not os.path.isdir(SAMPLES_DIR):
        log.info("%s folder created" % SAMPLES_DIR)
        os.mkdir(SAMPLES_DIR)

    # Check if IDA_SAMPLES_DIR folder is available
    if not os.path.isdir(IDA_SAMPLES_DIR):
        log.info("%s folder created" % IDA_SAMPLES_DIR)
        os.mkdir(IDA_SAMPLES_DIR)

    # Check if GHIDRA_PROJECT folder is available
    if not os.path.isdir(GHIDRA_PROJECT):
        log.info("%s folder created" % GHIDRA_PROJECT)
        os.mkdir(GHIDRA_PROJECT)

    # Check if GHIDRA_OUTPUT folder exists
    if not os.path.isdir(GHIDRA_OUTPUT):
        log.info("%s folder created" % GHIDRA_OUTPUT)
        os.mkdir(GHIDRA_OUTPUT)

    max_content_length_mb = os.getenv(
        "GHIDRAAAS_MAX_CONTENT_LENGTH_MB",
        str(DEFAULT_MAX_CONTENT_LENGTH_MB),
    )
    try:
        max_content_length_mb = int(max_content_length_mb)
    except ValueError:
        log.warning(
            "Invalid GHIDRAAAS_MAX_CONTENT_LENGTH_MB=%s, falling back to %s MB",
            max_content_length_mb,
            DEFAULT_MAX_CONTENT_LENGTH_MB,
        )
        max_content_length_mb = DEFAULT_MAX_CONTENT_LENGTH_MB

    if max_content_length_mb <= 0:
        log.warning(
            "Non-positive GHIDRAAAS_MAX_CONTENT_LENGTH_MB=%s, falling back to %s MB",
            max_content_length_mb,
            DEFAULT_MAX_CONTENT_LENGTH_MB,
        )
        max_content_length_mb = DEFAULT_MAX_CONTENT_LENGTH_MB

    app.config["MAX_CONTENT_LENGTH"] = max_content_length_mb * 1024 * 1024
    log.info("Configured upload limit: %s MB", max_content_length_mb)

    return


def _functions_list_output_path(sha256):
    return os.path.join(GHIDRA_OUTPUT, sha256 + "functions_list.json")


def _functions_list_detailed_output_path(sha256):
    return os.path.join(GHIDRA_OUTPUT, sha256 + "functions_list_a.json")


def _imports_list_output_path(sha256):
    return os.path.join(GHIDRA_OUTPUT, sha256 + "imports_list.json")


def _strings_list_output_path(sha256):
    return os.path.join(GHIDRA_OUTPUT, sha256 + "strings_list.json")


def _safe_offset_token(offset):
    return re.sub(r"[^0-9A-Za-z]", "_", offset)


def _decompiled_function_output_path(sha256, offset):
    return os.path.join(
        GHIDRA_OUTPUT,
        f"{sha256}_function_decompiled_{_safe_offset_token(offset)}.json",
    )


def _clear_cached_outputs(sha256):
    patterns = [
        os.path.join(GHIDRA_OUTPUT, f"{sha256}*"),
    ]
    removed = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            if os.path.isdir(path):
                continue
            try:
                os.remove(path)
                removed.append(path)
            except FileNotFoundError:
                continue
    if removed:
        log.debug("Cleared %s cached output artifact(s) for %s", len(removed), sha256)


def _lock_path(output_path):
    return output_path + ".lock"


def _headless_env():
    env = os.environ.copy()
    env.setdefault("ghidra_home", GHIDRA_PATH)
    env.setdefault("JAVA_HOME", DEFAULT_JAVA_HOME)

    path_entries = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
    java_bin = os.path.join(env["JAVA_HOME"], "bin")
    if java_bin not in path_entries:
        env["PATH"] = os.pathsep.join([java_bin] + [entry for entry in path_entries if entry])

    return env


def _start_background_command(command, lock_path, description):
    log_path = "/tmp/ghidraaas-background.log"
    open(lock_path, "a").close()

    def run_command():
        env = _headless_env()

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"\n[{description}] START {' '.join(shlex.quote(arg) for arg in command)}\n"
            )
            log_file.flush()
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
            exit_code = process.wait()
            log_file.write(f"[{description}] EXIT {exit_code}\n")
            log_file.flush()

        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass

        if exit_code != 0:
            log.warning("%s failed with exit code %s", description, exit_code)

    threading.Thread(target=run_command, daemon=True).start()
    log.debug("%s queued in background", description)


def _run_headless_command(command, description):
    log.debug("%s started", description)
    p = subprocess.Popen(command, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,
                         env=_headless_env())
    p.wait()
    print(''.join(s.decode("utf-8") for s in list(p.stdout)))
    log.debug("%s completed", description)


def _headless_post_script_command(sha256, output_path, script_name, *script_args):
    return [GHIDRA_HEADLESS,
            GHIDRA_PROJECT,
            sha256,
            "-process",
            sha256,
            "-noanalysis",
            "-scriptPath",
            GHIDRA_SCRIPT,
            "-postScript",
            script_name,
            *script_args,
            output_path,
            "-log",
            "ghidra_log.txt"]


def _functions_list_command(sha256, output_path, script_name):
    return _headless_post_script_command(sha256, output_path, script_name)


def _decompile_function_command(sha256, offset, output_path):
    return _headless_post_script_command(
        sha256,
        output_path,
        "FunctionDecompile.py",
        offset,
    )


def _ensure_functions_list_generation(sha256, script_name="FunctionsList.py", detailed=False):
    output_path = (
        _functions_list_detailed_output_path(sha256)
        if detailed else _functions_list_output_path(sha256)
    )
    if os.path.isfile(output_path):
        return output_path, False

    lock_path = _lock_path(output_path)
    if os.path.isfile(lock_path):
        return output_path, True

    command = _functions_list_command(sha256, output_path, script_name)
    _start_background_command(command, lock_path, f"{script_name} generation")
    return output_path, True


def _ensure_imports_list_generation(sha256):
    output_path = _imports_list_output_path(sha256)
    if os.path.isfile(output_path):
        return output_path, False

    lock_path = _lock_path(output_path)
    if os.path.isfile(lock_path):
        return output_path, True

    command = _headless_post_script_command(sha256, output_path, "ImportsList.py")
    _start_background_command(command, lock_path, "ImportsList.py generation")
    return output_path, True


def _ensure_strings_list_generation(sha256):
    output_path = _strings_list_output_path(sha256)
    if os.path.isfile(output_path):
        return output_path, False

    lock_path = _lock_path(output_path)
    if os.path.isfile(lock_path):
        return output_path, True

    command = _headless_post_script_command(sha256, output_path, "StringsList.py")
    _start_background_command(command, lock_path, "StringsList.py generation")
    return output_path, True


def _ensure_function_decompilation(sha256, offset):
    output_path = _decompiled_function_output_path(sha256, offset)
    if os.path.isfile(output_path):
        return output_path, False

    lock_path = _lock_path(output_path)
    if os.path.isfile(lock_path):
        return output_path, True

    command = _decompile_function_command(sha256, offset, output_path)
    _start_background_command(command, lock_path, f"FunctionDecompile generation for {offset}")
    return output_path, True


def get_project_metadata():
    """
    Return analyzed projects found on disk ordered by most recent first.
    """
    projects = []
    if not os.path.isdir(GHIDRA_PROJECT):
        return projects

    pattern = re.compile(r"^[a-fA-F0-9]{64}\.gpr$")
    for filename in os.listdir(GHIDRA_PROJECT):
        if not pattern.match(filename):
            continue
        project_path = os.path.join(GHIDRA_PROJECT, filename)
        if not os.path.isfile(project_path):
            continue
        sha256 = filename[:-4]
        projects.append({
            "job_id": sha256,
            "status": "done",
            "updated_at": os.path.getmtime(project_path),
        })

    projects.sort(key=lambda project: project["updated_at"], reverse=True)
    return projects


#############################################
#       GHIDRAAAS APIs                      #
#############################################

@app.route("/")
def index():
    """
    Index page
    """
    return ("Hi! This is Ghidraaas", 200)


@app.route("/ghidra/api/analyze_sample/", methods=["POST"])
def analyze_sample():
    """
    Upload a sample, save it on the file system,
    and launch Ghidra analysis.
    """
    try:
        if not request.files.get("sample"):
            raise BadRequest("sample is required")

        sample_content = request.files.get("sample").stream.read()
        if len(sample_content) == 0:
            raise BadRequest("Empty file received")

        stream = request.files.get("sample").stream
        sha256 = sha256_hash(stream)

        sample_path = os.path.join(SAMPLES_DIR, sha256)
        stream.seek(0)
        with open(sample_path, "wb") as f_out:
            f_out.write(stream.read())

        if not os.path.isfile(sample_path):
            raise BadRequest("File saving failure")

        log.debug("New sample saved (sha256: %s)" % sha256)

        # Check if the sample has been analyzed
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        _clear_cached_outputs(sha256)
        if not os.path.isfile(project_path):
            # Import the sample in Ghidra and perform the analysis
            command = [GHIDRA_HEADLESS,
                       GHIDRA_PROJECT,
                       sha256,
                       "-import",
                       sample_path]
            _run_headless_command(command, "Ghidra analysis")

        _ensure_functions_list_generation(sha256)
        _ensure_imports_list_generation(sha256)
        _ensure_strings_list_generation(sha256)

        os.remove(sample_path)
        log.debug("Sample removed")
        return ("Analysis completed", 200)

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Sample analysis failed")


@app.route("/ghidra/api/list_projects/")
def list_projects():
    """
    Return the analyzed projects currently available on disk.
    """
    try:
        return (json.dumps({"projects": get_project_metadata()}), 200)
    except Exception:
        raise BadRequest("Projects listing failed")


@app.route("/ghidra/api/get_functions_list_detailed/<string:sha256>")
def get_functions_list_detailed(sha256):
    """
    Given the sha256 of a sample, returns the list of functions.
    If the sample has not been analyzed, returns an error.
    """
    try:
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        # Check if the sample has been analyzed
        if os.path.isfile(project_path):
            output_path, in_progress = _ensure_functions_list_generation(
                sha256,
                script_name="FunctionsListA.py",
                detailed=True,
            )

            # Check if JSON response is available
            if os.path.isfile(output_path):
                with open(output_path) as f_in:
                    return (f_in.read(), 200)
            if in_progress:
                return (json.dumps({"status": "processing"}), 202)
            else:
                raise BadRequest("FunctionsList plugin failure")
        else:
            raise BadRequest("Sample has not been analyzed")

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Sample analysis failed")


@app.route("/ghidra/api/get_functions_list/<string:sha256>")
def get_functions_list(sha256):
    """
    Given the sha256 of a sample, returns the list of functions.
    If the sample has not been analyzed, returns an error.
    """
    try:
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        # Check if the sample has been analyzed
        if os.path.isfile(project_path):
            output_path, in_progress = _ensure_functions_list_generation(sha256)

            # Check if JSON response is available
            if os.path.isfile(output_path):
                with open(output_path) as f_in:
                    return (f_in.read(), 200)
            if in_progress:
                return (json.dumps({"status": "processing"}), 202)
            else:
                raise BadRequest("FunctionsList plugin failure")
        else:
            raise BadRequest("Sample has not been analyzed")

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Sample analysis failed")


@app.route("/ghidra/api/get_imports_list/<string:sha256>")
def get_imports_list(sha256):
    """
    Given the sha256 of a sample, returns imported symbols grouped by library.
    """
    try:
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        if os.path.isfile(project_path):
            output_path, in_progress = _ensure_imports_list_generation(sha256)

            if os.path.isfile(output_path):
                with open(output_path) as f_in:
                    return (f_in.read(), 200)
            if in_progress:
                return (json.dumps({"status": "processing"}), 202)
            raise BadRequest("ImportsList plugin failure")
        else:
            raise BadRequest("Sample has not been analyzed")

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Sample analysis failed")


@app.route("/ghidra/api/get_strings_list/<string:sha256>")
def get_strings_list(sha256):
    """
    Given the sha256 of a sample, returns discovered strings.
    """
    try:
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        if os.path.isfile(project_path):
            output_path, in_progress = _ensure_strings_list_generation(sha256)

            if os.path.isfile(output_path):
                with open(output_path) as f_in:
                    return (f_in.read(), 200)
            if in_progress:
                return (json.dumps({"status": "processing"}), 202)
            raise BadRequest("StringsList plugin failure")
        else:
            raise BadRequest("Sample has not been analyzed")

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Sample analysis failed")


@app.route("/ghidra/api/get_decompiled_function/<string:sha256>/<string:offset>")
def get_decompiled_function(sha256, offset):
    """
    Given a sha256, and an offset, returns the decompiled code of the
    function. Returns an error if the sample has not been analyzed by Ghidra,
    or if the offset does not correspond to a function
    """
    try:
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        # Check if the sample has been analyzed
        if os.path.isfile(project_path):
            output_path, in_progress = _ensure_function_decompilation(sha256, offset)

            # Check if the JSON response is available
            if os.path.isfile(output_path):
                with open(output_path) as f_in:
                    return (f_in.read(), 200)
            if in_progress:
                return (json.dumps({"status": "processing", "address": offset}), 202)
            else:
                raise BadRequest("FunctionDecompile plugin failure")
        else:
            raise BadRequest("Sample has not been analyzed")

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Sample analysis failed")


@app.route("/ghidra/api/analysis_terminated/<string:sha256>")
def analysis_terminated(sha256):
    """
    Given a sha256, and an offset, remove the Ghidra project
    associated to that sample. Returns an error if the project does
    not exist.
    """
    try:
        project_path = os.path.join(GHIDRA_PROJECT, sha256 + ".gpr")
        project_folder_path = os.path.join(GHIDRA_PROJECT, sha256 + ".rep")
        # Check if the sample has been analyzed
        if os.path.isfile(project_path) and os.path.isdir(project_folder_path):
            os.remove(project_path)
            log.debug("Ghidra project .gpr removed")
            shutil.rmtree(project_folder_path)
            log.debug("Ghidra project folder .rep removed")
            return ("Analysis terminated", 200)
        else:
            raise BadRequest("Sample does not exist.")

    except BadRequest:
        raise

    except Exception:
        raise BadRequest("Analysis terminated failed")


#############################################
#       GHIDRAAAS APIs for IDA plugin       #
#############################################

@app.route("/ghidra/api/ida_plugin_checkin/", methods=["POST"])
def ida_plugin_checkin():
    """
    Submit the .bytes file to ghidraaas for future decompilation
    """
    try:
        # Process the bytes file
        if not request.files.get("bytes"):
            raise BadRequest(".bytes file is required")

        sample_content = request.files.get("bytes").stream.read()
        if len(sample_content) == 0:
            raise BadRequest("Empty file .bytes received")

        # Process metadata associated to the bytes file
        if not request.files.get("data"):
            raise BadRequest("data is required")
        data = json.loads(request.files['data'].stream.read().decode('utf-8'))

        # Using md5, since IDA stores it in the IDB
        md5 = data.get('md5', None)
        if not md5:
            raise BadRequest("md5 hash is required")
        filename = data.get("filename", None)
        if not filename:
            raise BadRequest("filename is required")

        stream = request.files.get("bytes").stream
        binary_file_path = os.path.join(IDA_SAMPLES_DIR, "%s.bytes" % filename)
        stream.seek(0)
        with open(binary_file_path, "wb") as f_out:
            f_out.write(stream.read())

        if not os.path.isfile(binary_file_path):
            raise BadRequest("File saving failure")

        log.debug("New binary file saved (filename: %s)" % filename)
        return (json.dumps({
            "status": "ok"
        }), 200)

    except BadRequest:
        raise

    except Exception:
        log.exception("IDA plugin checkin failed")
        raise BadRequest("IDA plugin checkin failed")


@app.route("/ghidra/api/ida_plugin_get_decompiled_function/", methods=["POST"])
def ida_plugin_get_decompiled_function():
    """
    Run the script to decompile a function starting
    from the xml project exported from IDA.
    """
    try:
        # Process the xml file
        if not request.files.get("xml"):
            raise BadRequest(".xml file is required")

        sample_content = request.files.get("xml").stream.read()
        if len(sample_content) == 0:
            raise BadRequest("Empty file .xml received")

        # Process metadata associated with the request
        if not request.files.get("data"):
            raise BadRequest("data is required")
        data = json.loads(request.files['data'].stream.read().decode('utf-8'))

        # Using md5, since IDA stores it in the IDB
        md5 = data.get('md5', None)
        if not md5:
            raise BadRequest("md5 hash is required")
        filename = data.get("filename", None)
        if not filename:
            raise BadRequest("filename is required")
        address = data.get('address', None)
        if not address:
            raise BadRequest("address is required")

        stream = request.files.get("xml").stream
        xml_file_path = os.path.join(IDA_SAMPLES_DIR, "%s.xml" % filename)
        stream.seek(0)
        with open(xml_file_path, "wb") as f_out:
            f_out.write(stream.read())

        if not os.path.isfile(xml_file_path):
            raise BadRequest("File saving failure")

        log.debug("New xml file saved (filename: %s)" % filename)

        b_filename = filename + ".bytes"
        if not os.path.isfile(os.path.join(IDA_SAMPLES_DIR, b_filename)):
            raise BadRequest("Bytes file not exist")

        output_path = os.path.join(
            GHIDRA_OUTPUT, "%s_dec_%s.json" % (md5, address))

        cmd = [GHIDRA_HEADLESS,
               ".",
               "Temp",
               "-import",
               xml_file_path,
               '-scriptPath',
               GHIDRA_SCRIPT,
               '-postScript',
               'FunctionDecompile.py',
               address,
               output_path,
               "-noanalysis",
               "-deleteProject",
               "-log",
               "ghidra_log.txt"]

        # Execute Ghidra plugin
        log.debug("Ghidra analysis started")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        p.wait()
        print(''.join(s.decode("utf-8") for s in list(p.stdout)))
        log.debug("Ghidra analysis completed")

        # Check if the JSON response is available
        response = None
        if os.path.isfile(output_path):
            with open(output_path) as f_in:
                response = f_in.read()

        if response:
            try:
                os.remove(xml_file_path)
                log.debug("File %s removed", xml_file_path)
            except Exception:
                pass
            try:
                os.remove(output_path)
                log.debug("File %s removed", output_path)
            except Exception:
                pass
            return (response, 200)
        else:
            raise BadRequest("IDA plugin decompilation failed")

    except BadRequest:
        raise

    except Exception:
        log.exception("IDA plugin decompilation failed")
        raise BadRequest("IDA plugin decompilation failed")


@app.route("/ghidra/api/ida_plugin_checkout/", methods=["POST"])
def ida_plugin_checkout():
    """
    Remove files associated with the sample requesting checkout
    """
    try:
        if not request.json:
            raise BadRequest("json data required")

        j = json.loads(request.json)
        md5 = j.get("md5", None)
        if not md5:
            raise BadRequest("md5 hash is required")
        filename = j.get("filename", None)
        if not filename:
            raise BadRequest("filename is required")

        binary_file_path = os.path.join(IDA_SAMPLES_DIR, "%s.bytes" % filename)
        if os.path.isfile(binary_file_path):
            os.remove(binary_file_path)
            log.debug("File %s removed", binary_file_path)

        return ("OK", 200)

    except BadRequest:
        raise

    except Exception:
        log.exception("IDA plugin checkout failed")
        raise BadRequest("IDA plugin checkout failed")


#############################################
#       ERROR HANDLING                      #
#############################################
@app.errorhandler(BadRequest)
@app.errorhandler(RequestEntityTooLarge)
@app.errorhandler(HTTPException)
@app.errorhandler(Exception)
def handle_error(e):
    """
    Manage logging and responses in case of error.
    """
    if isinstance(e, RequestEntityTooLarge):
        limit_mb = app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024)
        return (f"Uploaded file exceeds the configured limit of {limit_mb} MB", 413)
    if isinstance(e, HTTPException):
        return (str(e), e.code)
    else:
        return (traceback.format_exc(), 500)


set_logger(True)
server_init()
DEFAULT_MAX_CONTENT_LENGTH_MB = 1024
