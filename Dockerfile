#
# Copyright The NOMAD Authors.
#
# This file is part of NOMAD. See https://nomad-lab.eu for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# This dockerfile describes an image that can be used to run the
# - nomad processing worker
# - nomad app (incl serving the gui)

# The dockerfile is multistaged to use a fat, more convinient build image and
# copy only necessities to a slim final image

# We use slim for the final image
FROM python:3.7-slim as final

# Build all python stuff in a python build image
FROM python:3.7-stretch as build
RUN mkdir /install

# Install linux package dependencies
RUN apt-get update
RUN apt-get install -y --no-install-recommends libgomp1
RUN apt-get install -y libmagic-dev curl make cmake swig libnetcdf-dev

# Install some specific dependencies necessary for the build process
RUN pip install --upgrade pip
RUN pip install fastentrypoints
RUN pip install pyyaml
RUN pip install numpy

# Install some specific dependencies to make use of docker layer caching
RUN pip install cython>=0.19
RUN pip install pandas
RUN pip install h5py
RUN pip install hjson
RUN pip install scipy
RUN pip install scikit-learn
RUN pip install ase==3.19.0
RUN pip install Pint
RUN pip install matid
RUN pip install mdtraj
RUN pip install mdanalysis

# Make will be necessary to build the docs with sphynx
RUN apt-get update && apt-get install -y make
RUN apt-get update && apt-get install -y vim

# Install pymolfile (required by some parsers)
RUN git clone -b nomad-fair https://gitlab.mpcdf.mpg.de/nomad-lab/pymolfile.git
WORKDIR /pymolfile/
RUN python3 setup.py install
RUN rm -rf /pymolfile

# Copy files and install nomad@FAIRDI
WORKDIR /install
COPY . /install
RUN python setup.py compile
RUN pip install .[all]
RUN ./generate_gui_artifacts.sh
WORKDIR /install/docs
RUN make html
RUN \
    find /usr/local/lib/python3.7/ -name 'tests' ! -path '*/networkx/*' -exec rm -r '{}' + && \
    find /usr/local/lib/python3.7/ -name 'test' -exec rm -r '{}' + && \
    find /usr/local/lib/python3.7/site-packages/ -name '*.so' -print -exec sh -c 'file "{}" | grep -q "not stripped" && strip -s "{}"' \;

# Built the GUI in the gui build image
FROM node:14.8 as gui_build
RUN mkdir -p /app
WORKDIR /app
ENV PATH /app/node_modules/.bin:$PATH
COPY gui/package.json /app/package.json
COPY gui/yarn.lock /app/yarn.lock
COPY gui/materia /app/materia
RUN yarn
COPY gui /app
COPY --from=build /install/gui/src/metainfo.json /app/src/metainfo.json
COPY --from=build /install/gui/src/searchQuantities.json /app/src/searchQuantities.json
COPY --from=build /install/gui/src/parserMetadata.json /app/src/parserMetadata.json
COPY --from=build /install/gui/src/toolkitMetadata.json /app/src/toolkitMetadata.json
COPY --from=build /install/gui/src/unitsData.js /app/src/unitsData.js
RUN yarn run build

# Copy all sources and assets to the GUI build image, build it there, and then
# slim down the contents before they are copied to the final image
RUN mkdir -p /encyclopedia
WORKDIR /encyclopedia
COPY dependencies/encyclopedia-gui/client /encyclopedia/
RUN npm install webpack webpack-cli
RUN npx webpack --mode=production
RUN rm -rf /encyclopedia/node_modules
RUN rm -rf /encyclopedia/src
RUN rm -f /encyclopedia/webpack.config.js
RUN rm -f /encyclopedia/.babelrc

# Third, create a slim final image
FROM final
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && apt-get install -y libmagic-dev curl vim zip unzip

# copy the sources for tests, coverage, qa, etc.
COPY . /app
WORKDIR /app
# transfer installed packages from dependency stage
COPY --from=build /usr/local/lib/python3.7/site-packages /usr/local/lib/python3.7/site-packages
# copy the documentation, its files will be served by the API
COPY --from=build /install/docs/.build /app/docs/.build
# copy the nomad command
COPY --from=build /usr/local/bin/nomad /usr/bin/nomad
# copy the gui
RUN mkdir -p /app/gui
COPY --from=gui_build /app/build /app/nomad/app/flask/static/gui
# copy the encyclopedia gui production code
COPY --from=gui_build /encyclopedia /app/nomad/app/flask/static/encyclopedia
# remove the developer config on the gui, will be generated by run.sh from nomad.yaml
RUN rm -f /app/nomad/app/flask/static/gui/env.js
RUN rm -f /app/nomad/app/flask/static/encyclopedia/conf.js
# build the python package dist
RUN python setup.py compile
RUN python setup.py sdist
RUN cp dist/nomad-lab-*.tar.gz dist/nomad-lab.tar.gz

RUN mkdir -p /app/.volumes/fs
RUN useradd -ms /bin/bash nomad
RUN chown -R nomad /app
RUN chmod a+rx run.sh
USER nomad

VOLUME /app/.volumes/fs

EXPOSE 8000
