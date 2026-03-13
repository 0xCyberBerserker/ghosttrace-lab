#!/usr/bin/env python3
# -*- coding: utf-8 -*-

##############################################################################
#                                                                            #
#  StringsList - Ghidra plugin                                               #
#                                                                            #
#  Export defined strings discovered in the program as JSON.                 #
#                                                                            #
##############################################################################

import json
import sys

from ghidra.program.model.data import StringDataInstance

try:
    args = getScriptArgs()
    response_dict = dict()

    if len(args) < 1:
        print("usage: ./StringsList.py output_path")
        sys.exit(0)

    output_path = args[0]
    listing = currentProgram.getListing()
    strings_list = []

    for data in listing.getDefinedData(True):
        try:
            string_instance = StringDataInstance.getStringDataInstance(data)
            if string_instance is None:
                continue
            value = string_instance.getStringValue()
            if value is None:
                continue
            text_value = str(value)
            if len(text_value.strip()) < 4:
                continue

            strings_list.append({
                "address": str(data.getAddress()),
                "length": len(text_value),
                "value": text_value,
            })
        except Exception:
            continue

    strings_list.sort(key=lambda item: (-item["length"], item["address"]))
    response_dict["status"] = "completed"
    response_dict["string_count"] = len(strings_list)
    response_dict["strings"] = strings_list

    print("Found %d strings" % len(strings_list))
    with open(output_path, "w") as f_out:
        json.dump(response_dict, f_out)
    print("Json saved to %s" % output_path)

except Exception:
    response_dict["status"] = "error"
    print(json.dumps(response_dict))
