import sys
from nomad.cli.parse import parse, normalize_all

# match and run the parser
backend = parse(sys.argv[1])
# run all normalizers
normalize_all(backend)

# get the 'main section' section_run as a metainfo object
section_run = backend.resource.contents[0].section_run[0]

# get the same data as JSON serializable Python dict
python_dict = section_run.m_to_dict()