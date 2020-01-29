import argparse
import json
import logging
import shutil
import sys

from argparse import RawTextHelpFormatter

from polyfile import logger, version

from .polymerge import merge, polyfile_type_graph
from . import polytracker

log = logger.getStatusLogger("PolyMerge")


def main(argv=None):
    parser = argparse.ArgumentParser(description='''A utility to merge the JSON output of `polyfile`
with a polytracker.json file from PolyTracker.

https://github.com/trailofbits/polyfile/
https://github.com/trailofbits/polytracker/
''', formatter_class=RawTextHelpFormatter)
    parser.add_argument('POLYFILE_JSON', type=argparse.FileType('r'), help='')
    parser.add_argument('POLYTRACKER_JSON', type=argparse.FileType('r'), help='')
    parser.add_argument('--cfg', '-c', type=str, default=None, help='Optional path to output a Graphviz .dot file representing the control flow graph of the program trace')
    parser.add_argument('--cfg-pdf', '-p', type=str, default=None, help='Similar to --cfg, but renders the graph to a PDF instead of outputting the .dot source')
    parser.add_argument('--type-hierarchy', '-t', type=str, default=None, help='Optional path to output a Graphviz .dot file representing the type hierarchy extracted from PolyFile')
    parser.add_argument('--type-hierarchy-pdf', '-y', type=str, default=None, help='Similar to --type-hierarchy, but renders the graph to a PDF instead of outputting the .dot source')
    parser.add_argument('--debug', '-d', action='store_true', help='Print debug information')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suppress all log output (overrides --debug)')
    parser.add_argument('--version', '-v',
                        action='version',
                        version=f"PolyMerge version {version.VERSION_STRING}\n",
                        help='Print PolyMerge\'s version information and exit'
    )
    parser.add_argument('-dumpversion',
                        action='version',
                        version=' '.join(map(str, version.__version__)),
                        help='Print PolyMerge\'s raw version information and exit'
    )

    if argv is None:
        argv = sys.argv

    args = parser.parse_args(argv[1:])

    if args.debug:
        logger.setLevel(logging.DEBUG)
    elif args.quiet:
        logger.setLevel(logging.CRITICAL)
    else:
        logger.setLevel(logger.STATUS)

    polyfile_json = json.load(args.POLYFILE_JSON)
    args.POLYFILE_JSON.close()
    program_trace = polytracker.parse(json.load(args.POLYTRACKER_JSON))
    args.POLYTRACKER_JSON.close()
    merged = merge(polyfile_json, program_trace)
    print(json.dumps(merged))
    if args.cfg is not None or args.cfg_pdf is not None:
        log.status("Reconstructing the runtime control flow graph...")
        cfg = program_trace.cfg
        dot = cfg.to_dot()#(merged_json_obj=merged)
        log.clear_status()
        if args.cfg is not None:
            with open(args.cfg, 'w') as cfg_file:
                cfg_file.write(dot.source)
            log.info(f"Saved CFG .dot graph to {args.cfg}")
        if args.cfg_pdf is not None:
            log.status("Rendering the runtime CFG to a PDF...")
            rendered_path = dot.render(args.cfg_pdf, cleanup=True)
            log.clear_status()
            if rendered_path != args.cfg_pdf:
                shutil.move(rendered_path, args.cfg_pdf)
            log.info(f"Saved CFG graph PDF to {args.cfg_pdf}")
    if args.type_hierarchy is not None or args.type_hierarchy_pdf is not None:
        log.status("Building the input file type hierarchy...")
        type_dominators: cfg.DAG = polyfile_type_graph(polyfile_json).dominator_forest
        dot = type_dominators.to_dot()
        if args.type_hierarchy:
            with open(args.type_hierarchy, 'w') as dot_file:
                dot_file.write(dot.source)
            log.info(f"Saved type hierarchy .dot graph to {args.type_hierarchy}")
        if args.type_hierarchy_pdf is not None:
            log.status("Rendering the type hierarchy to a PDF...")
            rendered_path = dot.render(args.type_hierarchy_pdf, cleanup=True)
            log.clear_status()
            if rendered_path != args.type_hierarchy_pdf:
                shutil.move(rendered_path, args.type_hierarchy_pdf)
            log.info(f"Saved type hierarchy PDF to {args.type_hierarchy_pdf}")


if __name__ == '__main__':
    main()
