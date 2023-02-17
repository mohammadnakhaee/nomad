/*
 * Copyright The NOMAD Authors.
 *
 * This file is part of NOMAD. See https://nomad-lab.eu for further info.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import React, {useCallback, useContext, useEffect, useMemo, useRef, useState} from 'react'
import PropTypes from 'prop-types'
import { atom, useRecoilState, useRecoilValue } from 'recoil'
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogContentText, FormControl, FormControlLabel,
  FormGroup, FormHelperText, Grid, IconButton, makeStyles, MenuItem, TextField, Tooltip, Typography
} from '@material-ui/core'
import { useHistory, useRouteMatch } from 'react-router-dom'
import Autocomplete from '@material-ui/lab/Autocomplete'
import Browser, {
  Adaptor, browserContext, Compartment, Content, formatSubSectionName, Item, ItemChip, laneContext, useLane
} from './Browser'
import { RawFileAdaptor } from './FileBrowser'
import {
  AttributeMDef, getUrlFromDefinition, isEditable, isReference, PackageMDef, QuantityMDef, quantityUsesFullStorage,
  removeSubSection, SectionMDef, SubSectionMDef, useMetainfo
} from './metainfo'
import { ArchiveTitle, DefinitionLabel, metainfoAdaptorFactory } from './MetainfoBrowser'
import { Matrix, Number } from './visualizations'
import Markdown from '../Markdown'
import { Overview } from './Overview'
import { Quantity as Q, useUnits } from '../../units'
import ArrowRightIcon from '@material-ui/icons/ArrowRight'
import ArrowDownIcon from '@material-ui/icons/ArrowDropDown'
import DownloadIcon from '@material-ui/icons/CloudDownload'
import SaveIcon from '@material-ui/icons/Save'
import AddIcon from '@material-ui/icons/AddCircle'
import CodeIcon from '@material-ui/icons/Code'
import DeleteIcon from '@material-ui/icons/Delete'
import grey from '@material-ui/core/colors/grey'
import classNames from 'classnames'
import { useApi } from '../api'
import { useErrors } from '../errors'
import { useDataStore, useEntryStoreObj } from '../DataStore'
import { SourceApiCall, SourceApiDialogButton, SourceJsonDialogButton } from '../buttons/SourceDialogButton'
import { Download } from '../entry/Download'
import Pagination from '../visualization/Pagination'
import SectionEditor from './SectionEditor'
import { useEntryStore } from '../entry/EntryContext'
import XYPlot from './XYPlot'
import {
  appendDataUrl, createEntryUrl, createUploadUrl, formatTimestamp, parseNomadUrl, refType, resolveInternalRef,
  resolveNomadUrl, systemMetainfoUrl, titleCase, isWaitingForUpdateTestId
} from '../../utils'
import { EntryButton } from '../nav/Routes'
import NavigateIcon from '@material-ui/icons/MoreHoriz'
import ReloadIcon from '@material-ui/icons/Replay'
import UploadIcon from '@material-ui/icons/CloudUpload'
import { apiBase } from '../../config'
import { Alert } from '@material-ui/lab'
import { complex, format } from 'mathjs'
import ReactJson from 'react-json-view'
import { range } from 'lodash'

export const configState = atom({
  key: 'config',
  default: {
    'showMeta': false,
    'showCodeSpecific': false,
    'showAllDefined': false
  }
})

const ArchiveBrowser = React.memo(({url}) => {
  const parsedUrl = useMemo(() => parseNomadUrl(url), [url])
  const {archive} = useEntryStoreObj(parsedUrl.deploymentUrl, parsedUrl.entryId, false, '*')
  const metainfo = useMetainfo(systemMetainfoUrl)
  const rootSectionDef = metainfo ? metainfo.getEntryArchiveDefinition() : null

  const searchOptions = useMemo(() => {
    return metainfo ? archiveSearchOptions(archive, metainfo) : []
  }, [archive, metainfo])

  const adaptor = useMemo(() => {
    if (!archive || !rootSectionDef) {
      return null
    }
    return archiveAdaptorFactory(url, archive, rootSectionDef)
  }, [url, archive, rootSectionDef])

  if (!adaptor) {
    return null
  }

  // For some reason, this hook does not work in all of the components used in
  // the Browser (notably: Quantity, QuantityItemPreview). In order to pass the
  // up-to-date unit information, we pass the hook value down the component
  // hierarchy.
  return (
    <Browser
      adaptor={adaptor}
      form={<ArchiveConfigForm searchOptions={searchOptions} data={archive}/>}
    />
  )
})
ArchiveBrowser.propTypes = ({
  url: PropTypes.string.isRequired
})
export default ArchiveBrowser

export const ArchiveSaveButton = React.memo(function ArchiveSaveButton(props) {
  const {editable, archiveHasChanges, saveArchive, reload} = useEntryStore()
  const [openErrorDialog, setOpenErrorDialog] = useState(false)
  const [disabled, setDisabled] = useState(false)

  const handleClick = useCallback(() => {
    saveArchive().catch(error => {
      if (error?.status === 409) {
        setOpenErrorDialog(true)
        setDisabled(true)
      }
    })
  }, [saveArchive])

  const handleReload = useCallback(() => {
    reload()
    setOpenErrorDialog(false)
  }, [reload])

  return <React.Fragment>
    {editable &&
      <IconButton
        disabled={!archiveHasChanges || disabled} color="primary"
        onClick={handleClick}
      >
        <Tooltip title="Save entry">
          <SaveIcon/>
        </Tooltip>
      </IconButton>
    }
    <Dialog
      open={openErrorDialog}
      aria-describedby="alert-dialog-description"
    >
      <DialogContent>
        <DialogContentText>
          The changes cannot be saved. The content has been modified by someone else.
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setOpenErrorDialog(false)}>OK</Button>
        <Button onClick={handleReload} autoFocus>Reload</Button>
      </DialogActions>
    </Dialog>
  </React.Fragment>
})

export const ArchiveReloadButton = React.memo(function ArchiveReloadButton(props) {
  const {reload} = useEntryStore()

  return <React.Fragment>
    <IconButton
      color="primary"
      onClick={reload}
    >
      <Tooltip title="Reload archive">
        <ReloadIcon/>
      </Tooltip>
    </IconButton>
  </React.Fragment>
})

export const ArchiveDeleteButton = React.memo(function ArchiveDeleteButton(props) {
  const history = useHistory()
  const {editable, uploadId, entryId} = useEntryStore()
  const {api} = useApi()
  const {raiseError} = useErrors()
  const [openDeleteConfirmDialog, setOpenDeleteConfirmDialog] = useState(false)

  const handleClick = useCallback(() => {
    setOpenDeleteConfirmDialog(true)
  }, [setOpenDeleteConfirmDialog])

  const handleDelete = useCallback(includeParentFolders => {
    setOpenDeleteConfirmDialog(false)
    const requestBody = {query: {entry_id: entryId}, include_parent_folders: includeParentFolders}
    api.post(`uploads/${uploadId}/action/delete-entry-files`, requestBody)
      .then(results => {
        history.push(`/user/uploads/upload/id/${uploadId}`)
      })
      .catch(err =>
        raiseError(err)
      )
  }, [uploadId, entryId, history, api, raiseError, setOpenDeleteConfirmDialog])

  return editable ? (
    <React.Fragment>
      <IconButton color="primary" onClick={handleClick}>
        <Tooltip title="Delete entry">
          <DeleteIcon/>
        </Tooltip>
      </IconButton>
      <Dialog
        open={openDeleteConfirmDialog}
        aria-describedby="alert-dialog-description"
      >
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            <b>Really delete this entry?</b>
          </DialogContentText>
          <DialogContentText>
            You can choose to delete only the mainfile, or to delete the mainfile and its folder.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDeleteConfirmDialog(false)} autoFocus>Cancel</Button>
          <Button onClick={() => handleDelete(false)}>Delete mainfile</Button>
          <Button onClick={() => handleDelete(true)}>Delete mainfile and folder</Button>
        </DialogActions>
      </Dialog>
    </React.Fragment>) : ''
})

const ArchiveConfigForm = React.memo(function ArchiveConfigForm({searchOptions, data}) {
  const [config, setConfig] = useRecoilState(configState)

  const handleConfigChange = event => {
    const changes = {[event.target.name]: event.target.checked}
    if (changes.showCodeSpecific) {
      changes.showAllDefined = !changes.showCodeSpecific
    } else if (changes.showAllDefined) {
      changes.showCodeSpecific = !changes.showAllDefined
    }
    setConfig({...config, ...changes})
  }

  const history = useHistory()
  const {url} = useRouteMatch()

  const entryId = data?.metadata?.entry_id

  return (
    <Box padding={0}>
      <FormGroup row style={{alignItems: 'center'}}>
        <Box style={{width: 350, height: 60}}>
          <Autocomplete
            options={searchOptions}
            getOptionLabel={(option) => option.name}
            style={{width: 500, marginTop: -20}}
            onChange={(_, value) => {
              if (value) {
                history.push(url + value.path)
              }
            }}
            renderInput={(params) => <TextField
              {...params} variant="filled"
              size="small" label="search" margin="normal"
            />}
          />
        </Box>
        <Box flexGrow={1}/>
        <Tooltip title="Enable to also show all code specific data">
          <FormControlLabel
            control={
              <Checkbox
                checked={config.showCodeSpecific}
                onChange={handleConfigChange}
                name="showCodeSpecific"
              />
            }
            label="code specific"
          />
        </Tooltip>
        <Tooltip title="Enable to also show metadata that is in principle available, but not within this entry">
          <FormControlLabel
            control={
              <Checkbox
                checked={config.showAllDefined}
                onChange={handleConfigChange}
                name="showAllDefined"
              />
            }
            label="all defined"
          />
        </Tooltip>
        <Tooltip title="Show the Metainfo definition on the bottom of each lane">
          <FormControlLabel
            control={
              <Checkbox
                checked={config.showMeta}
                onChange={handleConfigChange}
                name="showMeta"/>
            }
            label="definitions"
          />
        </Tooltip>
        {entryId && <Download
          tooltip="download the archive"
          url={`entries/${entryId}/archive/download?ignore_mime_type=true`}
          component={IconButton}
        >
          <DownloadIcon/>
        </Download>}
        <SourceApiDialogButton maxWidth="lg" fullWidth>
          <SourceApiCall/>
        </SourceApiDialogButton>
        <ArchiveReloadButton/>
        <ArchiveSaveButton/>
      </FormGroup>
    </Box>
  )
})
ArchiveConfigForm.propTypes = ({
  data: PropTypes.object.isRequired,
  searchOptions: PropTypes.arrayOf(PropTypes.object).isRequired
})

export const ArchiveReUploadButton = React.memo((props) => {
  const {uploadId, metadata, reload} = useEntryStore()
  const {api} = useApi()
  const {raiseError} = useErrors()

  const handleClick = useCallback((files) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.onchange = (event) => {
      const file = event.target.files[0]
      if (!file) {
        return
      }
      const formData = new FormData() // eslint-disable-line no-undef
      formData.set('file', file, metadata.entry_name)
      api.put(`uploads/${uploadId}/raw/?wait_for_processing=true`, formData)
        .then(() => {
          reload()
        })
        .catch(raiseError)
    }

    input.click()
  }, [api, metadata.entry_name, raiseError, reload, uploadId])

  return <IconButton onClick={handleClick}>
    <Tooltip title="Replace this entry's mainfile">
      <UploadIcon/>
    </Tooltip>
  </IconButton>
})

export function archiveAdaptorFactory(archiveRootUrl, archiveRootObj, rootSectionDef) {
  return new SectionAdaptor(archiveRootUrl, archiveRootObj, rootSectionDef)
}

function archiveSearchOptions(data, metainfo) {
  const options = []
  const optionDefs = {}

  function traverse(data, def, parentName, parentPath) {
    for (const key in data) {
      const childDef = def._properties[key]
      if (!childDef) {
        continue
      }

      const child = data[key]
      if (!child) {
        continue
      }
      const path = parentPath ? `${parentPath}/${key}` : `/${key}`
      const name = parentName ? `${parentName}.${childDef.name}` : childDef.name

      if (optionDefs[childDef._qualifiedName]) {
        continue
      }
      optionDefs[childDef._qualifiedName] = childDef
      const option = {
        name: name, // key
        data: data,
        def: childDef,
        path: path
      }
      options.push(option)

      if (childDef.m_def === SubSectionMDef) {
        const sectionDef = childDef.sub_section
        if (Array.isArray(child) && child.length > 0 && child[0]) {
          if (child.length > 1) {
            child.forEach((value, index) => traverse(value, sectionDef, name, `${path}:${index}`))
          } else {
            traverse(child[0], sectionDef, name, path)
          }
        } else {
          traverse(child, sectionDef, name, path)
        }
      }
    }
  }

  traverse(data, metainfo.getEntryArchiveDefinition(), null, null)
  return options
}

class ArchiveAdaptor extends Adaptor {
  /**
   * @param {*} objUrl An absolute url (string or a parsed url object), identifying a location in some archive.
   * @param {*} obj The data that objUrl points to = a location in some archive.
   * @param {*} def The metainfo definition of obj
   */
  constructor(objUrl, obj, def, isInEln) {
    super()
    this.objUrl = objUrl
    this.parsedObjUrl = parseNomadUrl(objUrl)
    if (!this.parsedObjUrl.isResolved) throw new Error(`Resolved url is required, got ${objUrl}`)
    if (this.parsedObjUrl.type !== refType.archive) throw new Error(`Bad url type, expected entry url, got ${objUrl}`)
    // Will be set when initializing the adaptor
    this.api = undefined
    this.dataStore = undefined
    this.entryIsEditable = undefined
    this.isInEln = isInEln === undefined && def.m_def === SectionMDef ? isEditable(def) : isInEln
    this.obj = obj // The data in the archive tree to display
    this.def = def
    this.external_refs = {}
  }

  async initialize(api, dataStore) {
    this.api = api
    this.dataStore = dataStore
    const {editable} = await dataStore.getEntryAsync(
      this.parsedObjUrl.deploymentUrl, this.parsedObjUrl.entryId, false, '*')
    this.entryIsEditable = editable
  }

  async adaptorFactory(objUrl, obj, def) {
    if (obj.m_def === PackageMDef) {
      // We're viewing an archive which contains metainfo definitions, and open the definitions node
      const metainfo = await this.dataStore.getMetainfoAsync(objUrl)
      return metainfoAdaptorFactory(metainfo._data.definitions)
    }

    if (def.m_def === SectionMDef) {
      if (obj.m_def) {
        // Override the def given by the schema with the potentially more specific
        // def given by the data
        const ref = obj.m_def_id ? `${obj.m_def}@${obj.m_def_id}` : obj.m_def
        const newDefUrl = resolveNomadUrl(ref, objUrl)
        def = await this.dataStore.getMetainfoDefAsync(newDefUrl)
      }
      const isInEln = this.isInEln || isEditable(def)
      return new SectionAdaptor(objUrl, obj, def, isInEln)
    }

    if (def.m_def === QuantityMDef) {
      if (def.type.type_kind === 'reference') {
        // Should only happen if the reference encountered has not been resolved, which can
        // happen if the reference is invalid or if it is of a type which we have no handler for.
        return new UnresolvedReferenceAdaptor(objUrl, obj, def)
      }

      return new QuantityAdaptor(objUrl, obj, def)
    }

    if (def.m_def === AttributeMDef) {
      return new AttributeAdaptor(objUrl, obj, def)
    }

    throw new Error('not implemented')
  }

  async itemAdaptor(key) {
    if (key === '_metainfo') {
      return metainfoAdaptorFactory(this.def)
    }

    if (key.startsWith('_external_ref')) {
      const ref = this.external_refs[key]
      if (!ref) return null

      const refUrl = createEntryUrl(apiBase, ref.upload_id, ref.entry_id)
      const {archive} = await this.dataStore.getEntryAsync(apiBase, ref.entry_id, false, '*')
      const metainfo = await this.dataStore.getMetainfoAsync(systemMetainfoUrl)
      const rootSectionDef = metainfo.getEntryArchiveDefinition()
      return this.adaptorFactory(refUrl, archive, rootSectionDef)
    }

    throw new Error('Unknown item key')
  }
}

class SectionAdaptor extends ArchiveAdaptor {
  async itemAdaptor(key) {
    const [name, index] = key.split(':')
    let urlSuffix = index ? `${name}/${index}` : name
    const property = this.def._properties[name] || (name === 'm_attributes' && this.def.attributes.find(attr => attr.name === index))
    let value = this.obj[name] === undefined || this.obj[name] === null ? property?.default : this.obj[name]
    if (property.m_def === QuantityMDef && quantityUsesFullStorage(property)) {
      value = value[index]
    }
    if (!property) {
      return super.itemAdaptor(key)
    } else if (property.m_def === SubSectionMDef) {
      const sectionDef = property.sub_section
      let subSectionAdaptor
      let subSectionIndex = -1
      if (property.repeats) {
        subSectionIndex = parseInt(index || 0)
        subSectionAdaptor = await this.adaptorFactory(
          appendDataUrl(this.parsedObjUrl, `${name}/${subSectionIndex}`), value[subSectionIndex], sectionDef)
      } else {
        subSectionAdaptor = await this.adaptorFactory(
          appendDataUrl(this.parsedObjUrl, name), value, sectionDef)
      }
      subSectionAdaptor.parentRelation = {
        parent: this.obj,
        subSectionDef: property,
        subSectionIndex: subSectionIndex
      }
      return subSectionAdaptor
    } else if (property.m_def === QuantityMDef) {
      // References: sections and quantities
      if (isReference(property)) {
        let reference = null
        if (property.shape.length === 0) {
          reference = value
          urlSuffix = name
        } else if (property.shape.length === 1) {
          const indexStr = key.split(':')[1]
          const index = parseInt(indexStr)
          reference = value[index]
          urlSuffix = `${name}/${index}`
        }
        if (!reference) {
          return this.adaptorFactory(
            appendDataUrl(this.parsedObjUrl, urlSuffix), value, property)
        }
        try {
          const resolvedUrl = resolveNomadUrl(reference, this.parsedObjUrl)
          if (resolvedUrl.type === refType.archive) {
            const {archive} = await this.dataStore.getEntryAsync(resolvedUrl.deploymentUrl, resolvedUrl.entryId, false, '*')
            const resolvedDef = property.type._referencedDefinition
            const resolvedObj = resolveInternalRef('/' + (resolvedUrl.path || ''), archive)
            return this.adaptorFactory(resolvedUrl, resolvedObj, resolvedDef)
          }
          throw new Error('Unhandled reference type')
        } catch (error) {
          // some sections cannot be resolved, because they are not part of the archive
          // user_id->user is one example
          return this.adaptorFactory(
            appendDataUrl(this.parsedObjUrl, urlSuffix), reference, property)
        }
      }
      // Regular quantities
      if (property.m_annotations?.browser) {
        if (property.m_annotations.browser[0].adaptor === 'RawFileAdaptor') {
          const deploymentUrl = this.parsedObjUrl.deploymentUrl
          const uploadId = this.parsedObjUrl.uploadId
          const path = this.obj[property.name]
          const uploadUrl = createUploadUrl(deploymentUrl, uploadId, path)
          return new RawFileAdaptor(uploadUrl, null, false)
        }
      }
      return this.adaptorFactory(appendDataUrl(this.parsedObjUrl, urlSuffix), value, property)
    } else if (property.m_def === AttributeMDef) {
      return this.adaptorFactory(
        appendDataUrl(this.parsedObjUrl, `m_attributes/${index}`),
        this.obj?.m_attributes[index],
        property)
    } else {
      throw new Error('Unknown metainfo meta definition')
    }
  }

  render() {
    return <Section
      section={this.obj}
      def={this.def}
      parentRelation={this.parentRelation}
      sectionIsInEln={this.isInEln}
      sectionIsEditable={this.entryIsEditable && this.isInEln}
    />
  }
}

class UnresolvedReferenceAdaptor extends ArchiveAdaptor {
  render() {
    return <UnresolvedReference value={this.obj} def={this.def}/>
  }
}

class QuantityAdaptor extends ArchiveAdaptor {
  async itemAdaptor(key) {
    const attribute = this.def?.attributes?.find(attr => attr.name === key)
    if (attribute) {
      const value = this.obj?.m_attributes?.[key]
      return await this.adaptorFactory(
        appendDataUrl(this.parsedObjUrl, `m_attributes/${key}`),
        value,
        attribute)
    }

    return super.itemAdaptor(key)
  }

  render() {
    if (quantityUsesFullStorage(this.def)) {
      return <FullStorageQuantity value={this.obj} def={this.def}/>
    } else {
      return <Quantity value={this.obj} def={this.def}/>
    }
  }
}

class AttributeAdaptor extends ArchiveAdaptor {
  render() {
    return <Attribute value={this.obj} def={this.def}/>
  }
}

const convertComplexArray = (real, imag) => {
  return Array.isArray(real)
    ? real.map((r, i) => convertComplexArray(r, imag[i]))
    : format(complex(real, imag), {notation: 'auto', precision: 4, lowerExp: -999, upperExp: 999})
}

function QuantityItemPreview({value, def}) {
  const units = useUnits()
  if (isReference(def)) {
    return <Box component="span" fontStyle="italic">
      <Typography component="span">reference ...</Typography>
    </Box>
  }
  if (def.m_annotations?.browser?.[0]?.render_value === 'HtmlValue' || def.m_annotations?.eln?.[0]?.component === 'RichTextEditQuantity') {
    return <Box component="span" whiteSpace="nowrap" fontStyle="italic">
      <Typography component="span">rich text</Typography>
    </Box>
  }
  if (def.type.type_data === 'nomad.metainfo.metainfo._JSON') {
    return <Box component="span" whiteSpace="nowrap" fontStyle="italic">
      <Typography component="span">JSON data</Typography>
    </Box>
  }
  if (def.shape.length > 0) {
    const dimensions = []
    let typeLabel = 'unknown'
    try {
      let current = value.re || value.im || value
      for (let i = 0; i < def.shape.length; i++) {
        dimensions.push(current.length)
        current = current[0]
      }
      if (def.type.type_kind === 'python') {
        typeLabel = 'list'
      } else {
        if (dimensions.length === 1) {
          typeLabel = 'vector'
        } else if (dimensions.length === 2) {
          typeLabel = 'matrix'
        } else {
          typeLabel = 'tensor'
        }
      }
    } catch (e) {
      console.error('Quantity shape did not fit quantity value.', e)
    }
    return <Box component="span" whiteSpace="nowrap" fontStyle="italic">
      <Typography component="span">
        {dimensions.map((dimension, index) => (
          <span key={index}>
            {index > 0 && <span>&nbsp;&times;&nbsp;</span>}{String(dimension)}
          </span>
        ))}&nbsp;{typeLabel}
      </Typography>
    </Box>
  } else {
    let finalValue
    if (def.type.type_data === 'nomad.metainfo.metainfo._Datetime') {
      finalValue = formatTimestamp(value)
    } else if (def.type.type_data.startsWith?.('complex')) {
      finalValue = convertComplexArray(value.re, value.im)
    } else {
      finalValue = value
    }

    let finalUnit
    if (def.unit) {
      const a = new Q(finalValue, def.unit).toSystem(units)
      finalValue = a.value()
      finalUnit = a.label()
    }
    return <Box component="span" whiteSpace="nowarp">
      <Number component="span" variant="body1" value={finalValue} exp={8}/>
      {finalUnit && <Typography component="span">&nbsp;{finalUnit}</Typography>}
    </Box>
  }
}

QuantityItemPreview.propTypes = ({
  value: PropTypes.any,
  def: PropTypes.object.isRequired
})

const QuantityValue = React.memo(function QuantityValue({value, def, ...more}) {
  const units = useUnits()

  const getRenderValue = useCallback(value => {
    let finalValue
    if (def.type.type_data === 'nomad.metainfo.metainfo._Datetime') {
      finalValue = formatTimestamp(value)
    } else if (def.type.type_data.startsWith?.('complex')) {
      finalValue = convertComplexArray(value.re, value.im)
    } else {
      finalValue = value
    }
    let finalUnit
    if (def.unit) {
      const systemUnitQ = new Q(finalValue, def.unit).toSystem(units)
      finalValue = systemUnitQ.value()
      finalUnit = systemUnitQ.label()
      if (more.unit) {
        const customUnitQ = systemUnitQ.to(more.unit)
        finalValue = customUnitQ.value()
        finalUnit = customUnitQ.label()
      }
    }
    return [finalValue, finalUnit]
  }, [def, more, units])

  const isMathValue = def.type.type_kind === 'numpy'
  if (isMathValue) {
    const [finalValue, finalUnit] = getRenderValue(value)
    if (def.shape.length > 0) {
      return <Box textAlign="center">
        <Matrix
          values={finalValue}
          shape={def.shape}
          invert={def.shape.length === 1}
          type={def.type.type_data}
          key={`matrix:${def.name}`}
        />
        <Typography noWrap variant="caption">
          ({def.shape.map((dimension, index) => <span key={index}>
            {index > 0 && <span>&nbsp;&times;&nbsp;</span>}{String(dimension)}
          </span>)}&nbsp;)
        </Typography>
        {finalUnit && <Typography noWrap>{finalUnit}</Typography>}
      </Box>
    } else {
      return <Number value={finalValue} exp={16} variant="body1" unit={finalUnit}/>
    }
  } else if (def.m_annotations?.browser?.[0]?.render_value === 'HtmlValue' || def.m_annotations?.eln?.[0]?.component === 'RichTextEditQuantity') {
    return <div dangerouslySetInnerHTML={{__html: value}}/>
  } else if (def.type?.type_data === 'nomad.metainfo.metainfo._JSON') {
    return <ReactJson
      name="value"
      src={value}
      enableClipboard={false}
      collapsed={2}
      displayObjectSize={false}
    />
  } else {
    if (def.type.type_data.startsWith?.('complex')) {
      value = convertComplexArray(value.re, value.im)

      return Array.isArray(value)
        ? <ul style={{margin: 0}}>
          {value.map((value, index) => <li key={index}><Typography>{value}</Typography></li>)}
        </ul>
        : <Typography>{value}</Typography>
    } else if (Array.isArray(value)) {
      return <ul style={{margin: 0}}>
        {value.map((value, index) => {
          const [finalValue] = getRenderValue(value)
          return <li key={index}>
            <Typography>{typeof finalValue === 'object' ? JSON.stringify(finalValue) : finalValue?.toString()}</Typography>
          </li>
        })}
      </ul>
    } else {
      const [finalValue] = getRenderValue(value)
      return <Typography>{typeof finalValue === 'object' ? JSON.stringify(finalValue) : finalValue?.toString()}</Typography>
    }
  }
})
QuantityValue.propTypes = ({
  value: PropTypes.any,
  def: PropTypes.object.isRequired,
  unit: PropTypes.string
})

const InheritingSections = React.memo(function InheritingSections({def, section, lane}) {
  const dataStore = useDataStore()
  const browser = useContext(browserContext)
  const originalInheritingSectionsRef = useRef([def, ...dataStore.getAllInheritingSections(def)])

  const currentInheritingSections = useMemo(() => {
    return [def, ...dataStore.getAllInheritingSections(def)]
  }, [dataStore, def])

  const getSelectionValue = useCallback((def) => {
    return getUrlFromDefinition(def, {deploymentUrl: apiBase}, true)
  }, [])

  const validSections = useMemo(() => {
    if (Object.keys(section).filter(key => key !== 'm_def').length === 0) {
      return originalInheritingSectionsRef.current
    } else {
      return currentInheritingSections
    }
  }, [originalInheritingSectionsRef, currentInheritingSections, section])

  const showSelection = useMemo(() => {
    return validSections.length > 1
  }, [validSections])

  const handleInheritingSectionsChange = useCallback((e) => {
    if (Object.keys(section).filter(key => key !== 'm_def').length !== 0) {
      if (!currentInheritingSections.includes(e.target.value)) {
        // TODO show alert dialog
        return
      }
    }
    section.m_def = e.target.value
    browser.invalidateLanesFromIndex(lane.index)
  }, [section, browser, lane, currentInheritingSections])

  if (!showSelection) {
    return null
  }

  return (
    <Box sx={{minWidth: 120}}>
      <FormControl fullWidth>
        <FormHelperText>Multiple specific sections are available</FormHelperText>
        <TextField
          value={getSelectionValue(def)}
          variant="filled"
          label="Select a section"
          data-testid={`inheriting:${def.name}`}
          onChange={handleInheritingSectionsChange}
          size="small"
          select
        >
          {validSections.map((inheritingSection, i) => {
            const sectionValue = getSelectionValue(inheritingSection)
            return (
              <MenuItem key={i} value={sectionValue}>
                {inheritingSection.name}
              </MenuItem>
            )
          })}
        </TextField>
      </FormControl>
    </Box>
  )
})
InheritingSections.propTypes = ({
  section: PropTypes.object.isRequired,
  def: PropTypes.object.isRequired,
  lane: PropTypes.object
})

export function getAllVisibleProperties(sectionDef) {
  const properties = sectionDef?.m_annotations?.eln?.[0]?.properties
  const visible = properties?.visible
  const hide = sectionDef?.m_annotations?.eln?.[0]?.hide || []
  let filteredProperties = sectionDef._allProperties
  if (visible) {
    const visiblePropertyNames = visible?.include || []
    filteredProperties = sectionDef._allProperties.filter(property => visiblePropertyNames.includes(property.name))
  }
  filteredProperties = filteredProperties.filter(property => !hide.includes(property.name))
  const editable = properties?.editable?.exclude || []
  const order = properties?.order || []
  const visibleProperties = filteredProperties.map(property => ({...property, _isEditable: !editable.includes(property.name)}))
  const quantities = visibleProperties.filter(property => property.m_parent_sub_section === "quantities")
  const sub_sections = visibleProperties.filter(property => property.m_parent_sub_section === "sub_sections")
  const reversedOrder = [...order].reverse()
  quantities.sort((a, b) => reversedOrder.indexOf(b.name) - reversedOrder.indexOf(a.name) || a.m_parent_index - b.m_parent_index)
  sub_sections.sort((a, b) => reversedOrder.indexOf(b.name) - reversedOrder.indexOf(a.name) || a.m_parent_index - b.m_parent_index)
  return [...quantities, ...sub_sections]
}

function Section({section, def, parentRelation, sectionIsEditable, sectionIsInEln}) {
  const {handleArchiveChanged} = useEntryStore() || {}
  const config = useRecoilValue(configState)
  const [showJson, setShowJson] = useState(false)
  const lane = useContext(laneContext)
  const history = useHistory()

  const navEntryId = useMemo(() => {
    return lane?.adaptor?.parsedObjUrl?.entryId
  }, [lane])

  const actions = useMemo(() => {
    const navButton = navEntryId && (
      <Grid item>
        <EntryButton entryId={navEntryId} component={IconButton} size="small">
          <NavigateIcon/>
        </EntryButton>
      </Grid>
    )

    const jsonButton = !sectionIsEditable ? (
      <Grid item>
        <SourceJsonDialogButton
          buttonProps={{size: 'small'}}
          tooltip={`Show section data as JSON`}
          title={`Underlying section data as JSON`}
          data={section}
        />
      </Grid>
    ) : (
      <Grid item>
        <IconButton onClick={() => setShowJson(value => !value)} size="small">
          <CodeIcon/>
        </IconButton>
      </Grid>
    )

    const handleDelete = () => {
      removeSubSection(
        parentRelation.parent,
        parentRelation.subSectionDef,
        parentRelation.subSectionIndex)
      handleArchiveChanged()
      history.push(lane.prev.path)
    }

    const deleteButton = sectionIsEditable && (
      <Grid item>
        <IconButton onClick={handleDelete} size="small">
          <DeleteIcon/>
        </IconButton>
      </Grid>
    )

    return <Grid container justifyContent="space-between" wrap="nowrap" spacing={1}>
      {navButton}{jsonButton}{deleteButton}
    </Grid>
  }, [navEntryId, setShowJson, sectionIsEditable, parentRelation, lane, history, handleArchiveChanged, section])

  const renderQuantityItem = useCallback((key, quantityName, quantityDef, value, disabled) => {
    const itemKey = quantityName ? `${key}:${quantityName}` : key
    const isDefault = value !== undefined && value !== null && (section[key] === undefined || section[key] === null)
    return (
      <Item key={itemKey} itemKey={itemKey} disabled={disabled}>
        <Box component="span" whiteSpace="nowrap" style={{maxWidth: 100, overflow: 'ellipses'}}>
          <Typography component="span">
            <Box fontWeight="bold" component="span">
              {quantityName || quantityDef.name}
            </Box>
          </Typography>{!disabled &&
          <span>&nbsp;=&nbsp;
            <QuantityItemPreview
              value={value}
              def={quantityDef}
            />
            </span>
        }
        </Box>
        {isDefault && <ItemChip label="default value"/>}
      </Item>
    )
  }, [section])

  const renderQuantity = useCallback(quantityDef => {
    const key = quantityDef.name
    const value = section[key] === undefined || section[key] === null ? quantityDef.default : section[key]
    const disabled = value === undefined
    if (!disabled && quantityDef.type.type_kind === 'reference' && quantityDef.shape.length === 1) {
      return <ReferenceValuesList key={key} quantityDef={quantityDef}/>
    }
    if (quantityUsesFullStorage(quantityDef)) {
      const storage = section[quantityDef.name] || {}
      return <React.Fragment key={key}>
        {Object.keys(storage).map(quantityName =>
          renderQuantityItem(key, quantityName, quantityDef, storage[quantityName]?.m_value, disabled)
        )}
      </React.Fragment>
    } else {
      return renderQuantityItem(key, null, quantityDef, value, disabled)
    }
  }, [section, renderQuantityItem])

  const allVisibleProperties = useMemo(() => getAllVisibleProperties(def), [def])

  if (!section) {
    console.error('section is not available')
    return null
  }

  const filter = config.showCodeSpecific ? def => !def.virtual : def => !def.virtual && !def.name.startsWith('x_')
  let sub_sections = allVisibleProperties.filter(prop => prop.m_def === SubSectionMDef)
  if (def.name === 'EntryArchive') {
    // put the most abstract data (last added data) first, e.g. results, metadata, workflow, run
    sub_sections = [...def.sub_sections]
    sub_sections.reverse()
  }
  const quantities = allVisibleProperties.filter(prop => prop.m_def === QuantityMDef)

  const subSectionsToRender = sub_sections
    .filter(subSectionDef => section[subSectionDef.name] || config.showAllDefined || sectionIsEditable)
    .filter(filter)
  const subSectionCompartment = (
    <Compartment title="sub sections">
      {subSectionsToRender
        .map(subSectionDef => {
          return <SubSection
            key={subSectionDef.name}
            subSectionDef={subSectionDef}
            section={section}
            editable={sectionIsEditable}
          />
        })
      }
    </Compartment>
  )

  let contents
  if (sectionIsEditable) {
    contents = <React.Fragment>
      {quantities.length > 0 && (
        <Compartment title="quantities">
          <SectionEditor sectionDef={def} section={section} showJson={showJson}/>
          <Box marginTop={2}>
            {quantities
              .filter(filter)
              .filter(quantityDef => !quantityDef.m_annotations?.eln)
              .map(renderQuantity)
            }
          </Box>
        </Compartment>
      )}
      {subSectionCompartment}
      {def.m_annotations?.plot && <SectionPlots sectionDef={def} section={section}/>}
    </React.Fragment>
  } else {
    const attributes = section?.m_attributes || {}
    contents = <React.Fragment>
      {subSectionCompartment}
      <Compartment title="quantities">
        {quantities
          .filter(quantityDef => section[quantityDef.name] !== undefined || config.showAllDefined || sectionIsInEln)
          .filter(filter)
          .map(renderQuantity)
        }
      </Compartment>
      {Object.keys(attributes).length > 0 && <Compartment title="attributes">
        {Object.keys(attributes).map(key => (
          <Item key={key} itemKey={`m_attributes:${key}`}>{key}</Item>
        ))}
      </Compartment>}
      {def.m_annotations?.plot && <SectionPlots sectionDef={def} section={section}/>}
    </React.Fragment>
  }
  const eln = def?.m_annotations?.eln
  const laneWidth = (eln && eln.length > 0 ? eln[0].lane_width : undefined)
  const otherProps = (laneWidth ? {minWidth: laneWidth, maxWidth: laneWidth} : undefined)
  return (
    <Content {...otherProps}>
      {sectionIsEditable && sectionIsInEln && (
        <InheritingSections def={def} section={section} lane={lane}/>
      )}
      <ArchiveTitle def={def} data={section} kindLabel="section" actions={actions}/>
      <Overview section={section} def={def}/>
      {contents}
      <ExternalReferences/>
      <Meta def={def}/>
    </Content>
  )
}

Section.propTypes = ({
  section: PropTypes.object.isRequired,
  def: PropTypes.object.isRequired,
  parentRelation: PropTypes.object,
  sectionIsEditable: PropTypes.bool,
  sectionIsInEln: PropTypes.bool
})

export function getItemLabelKey(sectionDef) {
  let itemLabelKey = sectionDef.more?.label_quantity
  if (!itemLabelKey) {
    itemLabelKey = ['name', 'type', 'id'].find(key => (
      sectionDef._properties[key] && sectionDef._properties[key].m_def === QuantityMDef
    ))
  }
  return itemLabelKey
}

function SubSection({subSectionDef, section, editable}) {
  const {handleArchiveChanged} = useEntryStore() || {}
  const lane = useLane()
  const history = useHistory()
  const {label, getItemLabel} = useMemo(() => {
    const sectionDef = subSectionDef.sub_section
    let itemLabelKey = getItemLabelKey(sectionDef)
    let labelQuantity = itemLabelKey && sectionDef._properties[itemLabelKey]
    if (labelQuantity && quantityUsesFullStorage(labelQuantity)) {
      // We do not yet support label quantities that use full storage
      labelQuantity = undefined
      itemLabelKey = undefined
    }
    const getItemLabel = item => {
      if (labelQuantity) {
        const value = item[itemLabelKey]
        if (value) {
          return <QuantityValue value={item[itemLabelKey]} def={labelQuantity}/>
        }
      } else if (itemLabelKey) {
        return item[itemLabelKey]
      }
      return null
    }
    return {
      label: formatSubSectionName(subSectionDef.name),
      getItemLabel: getItemLabel
    }
  }, [subSectionDef])

  const handleAdd = useCallback(() => {
    let subSectionKey = subSectionDef.name
    if (subSectionDef.repeats) {
      let values = section[subSectionDef.name]
      if (!values) {
        values = []
        section[subSectionDef.name] = values
      }
      values.push({})
      if (values.length > 1) {
        subSectionKey += `:${values.length - 1}`
      }
    } else {
      section[subSectionDef.name] = {}
    }
    handleArchiveChanged()
    history.push(`${lane.path}/${subSectionKey}`)
  }, [subSectionDef, section, lane, history, handleArchiveChanged])

  const values = section[subSectionDef.name]
  const showList = subSectionDef.repeats && values && values.length > 1
  const actions = editable && (subSectionDef.repeats || !values) && (
    <Box marginRight={!showList && values ? -1 : 2}>
      <IconButton data-testid={`subsection:${subSectionDef.name}`} onClick={handleAdd} size="small">
        <AddIcon style={{fontSize: 20}}/>
      </IconButton>
    </Box>
  )

  if (showList) {
    return <PropertyValuesList
      label={label || 'list'} actions={actions}
      values={(section[subSectionDef.name] || []).map(getItemLabel)}
    />
  } else {
    return (
      <Item
        itemKey={subSectionDef.name} disabled={!values}
        actions={actions}
      >
        <Typography component="span">
          <Box fontWeight="bold" component="span">
            {label}
          </Box>
        </Typography>
      </Item>
    )
  }
}

SubSection.propTypes = ({
  subSectionDef: PropTypes.object.isRequired,
  section: PropTypes.object.isRequired,
  editable: PropTypes.bool
})

function ReferenceValuesList({quantityDef}) {
  const lane = useContext(laneContext)
  const values = useMemo(() => lane.adaptor.obj[quantityDef.name].map(() => null), [lane.adaptor.obj, quantityDef.name])
  return <PropertyValuesList
    values={values}
    label={quantityDef.name}/>
}

ReferenceValuesList.propTypes = ({
  quantityDef: PropTypes.object.isRequired
})

const usePropertyValuesListStyles = makeStyles(theme => ({
  root: {
    margin: `0 -${theme.spacing(1)}px`,
    padding: `0 ${theme.spacing(1)}px`,
    width: '100%',
    display: 'flex',
    flexDirection: 'row',
    wrap: 'nowrap',
    alignItems: 'center'
  },
  title: {
    flexGrow: 1,
    color: theme.palette.text.primary,
    textDecoration: 'none',
    margin: `0 -${theme.spacing(1)}px`,
    whiteSpace: 'nowrap',
    display: 'flex',
    fontWeight: 'bold'
  },
  selected: {
    backgroundColor: theme.palette.primary.main,
    color: theme.palette.primary.contrastText,
    whiteSpace: 'nowrap'
  },
  unSelected: {
    '&:hover': {
      backgroundColor: grey[300]
    }
  },
  actions: {}
}))

/**
 * Displays a list of values that can be collapsed. Long lists are paginated in
 * order to prevent issues with rendering.
 */
export function PropertyValuesList({label, values, actions, nTop, nBottom, pageSize}) {
  const classes = usePropertyValuesListStyles()
  const [open, setOpen] = useState(false)
  const [nShownTop, setNShownTop] = useState(0)
  const [nShownBottom, setNShownBottom] = useState(0)
  const lane = useContext(laneContext)
  const selected = lane.next && lane.next.key
  const showSelected = !open && selected && selected.startsWith(label + ':')

  const item = (index, item) => {
    return <Item key={index} itemKey={`${label}:${index}`}>
      <Box display="flex" flexDirection="row" flexGrow={1}>
        <Box component="span" marginLeft={2}>
          {item && typeof item === 'object'
            ? item // item should be a react component
            : <Typography component="span">{item || index}</Typography>
          }
        </Box>
      </Box>
    </Item>
  }

  const topStart = 0
  const topEnd = Math.min(values.length, nTop + nShownTop)
  const bottomStart = Math.max(topEnd, values.length - nBottom - nShownBottom)
  const bottomEnd = values.length

  return <React.Fragment>
    <div className={classNames(
      classes.root, showSelected ? classes.selected : classes.unSelected)}
    >
      <Typography onClick={() => setOpen(!open)} className={classes.title}>
        {open ? <ArrowDownIcon/> : <ArrowRightIcon/>}
        <span role="item-list">{label}</span>
      </Typography>
      {actions && <div className={classes.actions}>
        {actions}
      </div>}
    </div>
    {open &&
      <div data-testid={`item-list:${label}`}>
        {range(topStart, topEnd).map((index) => item(index, values[index]))}
        {topEnd < bottomStart && <Box marginLeft={0.8}>
          <Pagination
            showMore
            showLess={nShownTop > 0}
            onMore={() => setNShownTop(x => Math.min(bottomStart, x + pageSize))}
            onLess={() => setNShownTop(x => Math.max(0, x - pageSize))}
            variant="down"
            data-testid="propertyvalueslist-pagination-down"
          />
          <Pagination
            showMore
            showLess={nShownBottom > 0}
            onMore={() => setNShownBottom(x => Math.min(values.length - nShownTop - nBottom, x + pageSize))}
            onLess={() => setNShownBottom(x => Math.max(0, x - pageSize))}
            variant="up"
            data-testid="propertyvalueslist-pagination-up"
          />
        </Box>}
        {range(bottomStart, bottomEnd).map((index) => item(index, values[index]))}
      </div>
    }
  </React.Fragment>
}

PropertyValuesList.propTypes = ({
  label: PropTypes.string.isRequired,
  values: PropTypes.arrayOf(PropTypes.object).isRequired,
  actions: PropTypes.node,
  nTop: PropTypes.number,
  nBottom: PropTypes.number,
  pageSize: PropTypes.number
})

PropertyValuesList.defaultProps = ({
  nTop: 50,
  nBottom: 5,
  pageSize: 25
})

export const SectionPlots = React.memo(function SectionPlots({section, sectionDef}) {
  const plot = sectionDef.m_annotations?.plot
  const [selected, setSelected] = useState([0])
  const plots = useMemo(() => {
    const plots = (Array.isArray(plot) ? [...plot] : [{...plot}])
    plots.forEach(plot => {
      if (!('label' in plot)) {
        const yAxis = plot.y || plot['y_axis'] || plot['yAxis']
        const pathParts = Array.isArray(yAxis) ? ['unnamed'] : yAxis.split('/')
        plot.label = pathParts[pathParts.length - 1]
      }
    })
    return plots
  }, [plot])

  useEffect(() => {
    setSelected([0])
  }, [plots.length])

  if (plots.length < 1 || selected.find(index => index >= plots.length)) {
    return null
  }

  return <Compartment title="plot">
    <Box minWidth={500}>
      {plots.length > 1 && <TextField
        select variant="filled" size="small" fullWidth label={'Shown plots'} style={{marginBottom: 2}}
        SelectProps={{
          multiple: true,
          value: selected,
          onChange: event => setSelected(event.target.value),
          renderValue: newSelected => newSelected.map(index => titleCase(plots[index].label))?.join(', ')
        }}
      >
        {plots.map((plot, index) => (
          <MenuItem key={index} value={index}>
            <Checkbox
              checked={selected.findIndex(selectedIndex => selectedIndex === index) >= 0}
            />
            {titleCase(plot.label)}
          </MenuItem>
        ))}
      </TextField>}
      {selected.map(index => plots?.[index])
        ?.map((plot, index) => (
          <XYPlot
            key={index}
            sectionDef={sectionDef}
            section={section}
            plot={plot}
            title={plot.label}
          />
        ))
      }
    </Box>
  </Compartment>
})
SectionPlots.propTypes = {
  sectionDef: PropTypes.object.isRequired,
  section: PropTypes.object
}

function FullStorageQuantity({value, def}) {
  const attributes = value.m_attributes || {}
  return <Quantity value={value.m_value} def={def} unit={value.m_unit}>
    {Object.keys(attributes).length > 0 && <Compartment title="attributes">
      {Object.keys(attributes).map(key => (
        <Item key={key} itemKey={key}>{key}</Item>
      ))}
    </Compartment>}
  </Quantity>
}

FullStorageQuantity.propTypes = ({
  value: PropTypes.any,
  def: PropTypes.object.isRequired
})

function Quantity({value, def, unit, children}) {
  const {prev} = useLane()
  return <Content>
    <ArchiveTitle def={def} data={value} kindLabel="value"/>
    {def.m_annotations?.plot && (
      <Compartment title="plot">
        <XYPlot
          section={prev.adaptor.obj}
          sectionDef={prev.adaptor.def}
          plot={def.m_annotations?.plot[0]}
          title={def.name}
        />
      </Compartment>
    )}
    <Compartment title="value">
      <QuantityValue
        value={value}
        def={def}
        unit={unit}
      />
    </Compartment>
    {children}
    <Meta def={def}/>
    <ExternalReferences/>
  </Content>
}

Quantity.propTypes = ({
  value: PropTypes.any,
  def: PropTypes.object.isRequired,
  unit: PropTypes.string,
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.node),
    PropTypes.node
  ])
})

function Attribute({value, def}) {
  return <Content>
    <ArchiveTitle def={def} data={value} kindLabel="attribute"/>
    <Compartment title="value">
      <QuantityValue
        value={value}
        def={def}
      />
    </Compartment>
    <Meta def={def}/>
  </Content>
}

Attribute.propTypes = ({
  value: PropTypes.any,
  def: PropTypes.object.isRequired
})

function UnresolvedReference({value, def}) {
  const refTypeName = def?.type?._referencedDefinition?.name
  const refTypeQualifiedName = def?.type?._referencedDefinition?._qualifiedName
  const isOk = ['nomad.metainfo.metainfo.User'].includes(refTypeQualifiedName) // expected to not be resolvable
  return <Content>
    <ArchiveTitle def={def} data={value} kindLabel="value"/>
    <Compartment title="reference">
      {!isOk && <Typography color="error">Cannot resolve reference.</Typography>}
      <Typography><b>Reference type:</b></Typography>
      <Typography>{refTypeName || 'unknown'}</Typography>
      <Typography><b>Reference value:</b></Typography>
      <Typography>{value}</Typography>
    </Compartment>
    <Meta def={def}/>
  </Content>
}

UnresolvedReference.propTypes = ({
  value: PropTypes.any,
  def: PropTypes.object.isRequired
})

const useMetaStyles = makeStyles(theme => ({
  description: {
    marginTop: theme.spacing(1)
  },
  graph: {
    marginTop: theme.spacing(3)
  },
  metainfo: {
    marginBottom: theme.spacing(2)
  },
  metainfoItem: {
    fontWeight: 'bold'
  }
}))

export function Meta({def}) {
  const classes = useMetaStyles()
  const config = useRecoilValue(configState)
  if (!config.showMeta) {
    return null
  }
  return <Compartment title="meta" color="primary">
    <div className={classes.metainfo}>
      <Item itemKey="_metainfo">
        <DefinitionLabel classes={{root: classes.metainfoItem}} def={def} isDefinition component="span"/>
      </Item>
    </div>
    <Markdown classes={{root: classes.description}}>{def.description}</Markdown>
  </Compartment>
}

Meta.propTypes = ({
  def: PropTypes.object
})

const baseQuery = {
  'exclude': [
    'atoms',
    'only_atoms',
    'files',
    'quantities',
    'dft.quantities',
    'optimade',
    'dft.labels',
    'dft.geometries'
  ],
  'required': {
    'metadata': '*'
  },
  'owner': 'visible',
  'pagination': {
    'order_by': 'upload_create_time', 'order': 'desc', 'page_size': 20
  }
}

function ExternalReferences() {
  const lane = useLane()
  const [searchResults, setSearchResults] = useState(null)

  const {api} = useApi()
  const {raiseError} = useErrors()

  const source = lane.adaptor

  const entryId = source.parsedObjUrl.entryId
  const dataPath = source.parsedObjUrl.path || '/'

  const performSearch = () => {
    if (searchResults) return
    const referencing_query = Object.assign({}, baseQuery, {
      'query': {
        'entry_references.target_entry_id': entryId,
        'entry_references.target_path': dataPath
      }
    })
    api.query('entries', referencing_query, {noLoading: true}).then((data) => {
      source.external_refs = Object.fromEntries(data.data.map((entry, index) => {
        entry.entry_references = entry.entry_references.filter(ref => ref.target_entry_id === entryId && ref.target_path === dataPath)
        return ['_external_ref_' + index, entry]
      }))
      setSearchResults(Object.values(source.external_refs))
    }).catch(raiseError)
  }

  const entry_list = (list) => {
    return list.map((ref, index) => (
      <Item itemKey={'_external_ref_' + index} key={index}><Typography component="span">
        <Box fontWeight="bold" component="span">{ref.mainfile}</Box>
        &nbsp;=&nbsp;
        <Box component="span" fontStyle="italic">entry ...</Box>
        {ref.entry_references?.map(
          (ref, index) => <Typography key={index} variant="body2">{ref.source_path}</Typography>
        )}
      </Typography></Item>
    ))
  }

  return <Compartment title="referenced by" startCollapsed={true} onUnfold={performSearch}>
    {searchResults
      ? searchResults.length > 0
        ? searchResults.length === 20
          ? <Tooltip title="Only showing at most the latest 20 entries.">
            {entry_list(searchResults)}
          </Tooltip>
          : entry_list(searchResults)
        : <Alert severity={'info'}>not referenced by other entries</Alert>
      : <Alert severity={'info'} data-testid={isWaitingForUpdateTestId}>loading...</Alert>}
  </Compartment>
}
