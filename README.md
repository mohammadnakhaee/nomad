[![pipeline status](https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-FAIR/badges/master/pipeline.svg)](https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-FAIR/commits/master)
[![coverage report](https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-FAIR/badges/master/coverage.svg)](https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-FAIR/commits/master)

This project implements the new *nomad@FAIRDI* infrastructure. Contrary to its NOMAD CoE
predecessor, it implements the NOMAD Repository and NOMAD Archive functionality within
a single cohesive application. This project provides all necessary artifacts to develop,
test, deploy, and operate the NOMAD Respository and Archive, e.g. at
[https://repository.nomad-coe.eu/app/gui](https://repository.nomad-coe.eu/app/gui).

In the future, this project's aim is to integrate more NOMAD CoE components, like the NOMAD
Encyclopedia and NOMAD Analytics Toolkit, to fully integrate NOMAD with one GUI and consistent
APIs. Furthermore, this projects aims at establishing NOMAD as a distributed platform for
material science data sharing and management. This includes the on-site deployment of
NOMAD as a standalone service (*oasis*), the federated use of NOMAD through a
serious of full and partial *mirrors*, the integration of 3rd party material science
databases (i.e. [Aflow](http://www.aflow.org/), [OQMD](http://oqmd.org/),
[Materials Project](https://materialsproject.org/)), and support for open APIs and
standards like the [Optimade](http://www.optimade.org/) API.


## Getting started

Read the [docs](https://repository.nomad-coe.eu/app/docs). The documentation is also part
of the source code. It covers aspects like introduction, architecture, development setup/deployment,
contributing, and API reference.


## Change log

Omitted versions are plain bugfix releases with only minor changes and fixes.

### v0.7.1
- Download of archive files based on search queries
- minor bugfixes

### v0.7.0
- User metadata editing and datasets with DOIs
- Revised GUI lists (entries, grouped entries, datasets, uploads)
- Keycloak based user management
- Rawfile preview
- no dependencies with the old NOMAD CoE Repository

### v0.6.2
- GUI performance enhancements
- API /raw/query endpoint takes file pattern to further filter download contents and
  strips potential shared path prefixes for a cleaner download .zip
- Stipped common path prefixes in raw file downloads
- minor bugfixes

### v0.6.0
- GUI URL, and API endpoint that resolves NOMAD CoE legacy PIDs
- Support for datasets in the GUI
- more flexible search python module and repo API
- support for external_id
- support for code-based raw_id
- Optimade API 0.10.0
- GUI supports Optimade filter query and other quantities
- minor bugfixes

### v0.5.2
- allows to download large files over longer time period
- streamlined deployment without API+GUI proxy
- minor bugfixes

### v0.5.1
- integrated parsers Dmol3, qbox, molcas, fleur, and onetep
- API endpoint for query based raw file download
- improvements to admin cli: e.g. clean staging files, reprocess uploads based on codes
- improved error handling in the GUI
- lots of parser bugfixes
- lots of minor bugfixes

### v0.5.0
The first production version of nomad@fairdi as the upload API and gui for NOMAD
- Production ready software and deployments (term agreements, better GUI docs)
- Raw file API with support to list directories. This replaces the `files` calculation
  metadata key. It was necessary due to arbitrary large lists of *auxfiles* in some
  calculations.
- Search interface that contains all features of the CoE Repository GUI.
- Refactored search API that allows to search for entries (paginated + scroll),
  metrics based on quantity aggregations (+ paginated entries), quantity aggregations
  with all values via `after` key (+ paginated entries).
- reprocessing of published results (e.g. after parser/normalizer improvements)
- mirror functionality
- refactored command line interface (CLI)
- potential GUI user tracking capabilities
- many minor bugfixes

### v0.4.7
- more migration scripts
- minor bugfixes

### v0.4.6
- admin commands to directly manipulate upload data
- additional migration scripts
- fixed system normalizer to understand indexed atom labels correctly
- many minor bugfixes

### v0.4.5
- improved uploads view with published uploads
- support for publishing to the existing nomad CoE repository
- many minor bugfixes

### v0.4.4
- improved GUI navigation
- support for multiple domains
- info API endpoint
- metainfo browser
- support for latest exciting version
- bugfixes in system normalization
- many minor bugfixes

### v0.4.3
- more flexible celery routing
- config via nomad.yml
- repo_db can be disabled
- publishing of calculations with failed processing
- cli for managing running processing tasks

### v0.4.2
- bugfixes regarding the migration
- better migration configurability and reproducibility
- scales to multi node kubernetes deployment
