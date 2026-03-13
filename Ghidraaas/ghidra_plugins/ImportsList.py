#!/usr/bin/env python3
# -*- coding: utf-8 -*-

##############################################################################
#                                                                            #
#  ImportsList - Ghidra plugin                                               #
#                                                                            #
#  Export imported symbols grouped by library as JSON.                       #
#                                                                            #
##############################################################################

import json
import sys

try:
    args = getScriptArgs()
    response_dict = dict()

    if len(args) < 1:
        print("usage: ./ImportsList.py output_path")
        sys.exit(0)

    output_path = args[0]
    symbol_table = currentProgram.getSymbolTable()
    imports_by_library = dict()
    import_count = 0

    for symbol in symbol_table.getExternalSymbols():
        parent_symbol = symbol.getParentSymbol()
        library_name = parent_symbol.getName() if parent_symbol else "EXTERNAL"
        import_name = symbol.getName(True) if hasattr(symbol, "getName") else str(symbol)
        symbol_address = str(symbol.getAddress()) if symbol.getAddress() else None

        if library_name not in imports_by_library:
            imports_by_library[library_name] = []

        imports_by_library[library_name].append({
            "name": import_name,
            "address": symbol_address,
        })
        import_count += 1

    normalized_imports = dict()
    for library_name in sorted(imports_by_library.keys()):
        normalized_imports[library_name] = sorted(
            imports_by_library[library_name],
            key=lambda item: item["name"].lower(),
        )

    response_dict["status"] = "completed"
    response_dict["import_count"] = import_count
    response_dict["library_count"] = len(normalized_imports)
    response_dict["libraries"] = sorted(normalized_imports.keys())
    response_dict["imports_by_library"] = normalized_imports

    print("Found %d imports across %d libraries" % (import_count, len(normalized_imports)))
    with open(output_path, "w") as f_out:
        json.dump(response_dict, f_out)
    print("Json saved to %s" % output_path)

except Exception:
    response_dict["status"] = "error"
    print(json.dumps(response_dict))
