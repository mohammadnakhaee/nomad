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
import React from 'react'
import PropTypes from 'prop-types'
import { withStyles, Link, Typography, Tooltip, IconButton, TablePagination } from '@material-ui/core'
import { compose } from 'recompose'
import { withRouter } from 'react-router'
import DataTable from '../DataTable'
import Quantity from '../Quantity'
import { Link as RouterLink } from 'react-router-dom'
import DetailsIcon from '@material-ui/icons/MoreHoriz'
import EditUserMetadataDialog from '../EditUserMetadataDialog'
import DownloadButton from '../DownloadButton'
import PublicIcon from '@material-ui/icons/Public'
import UploaderIcon from '@material-ui/icons/AccountCircle'
import SharedIcon from '@material-ui/icons/SupervisedUserCircle'
import PrivateIcon from '@material-ui/icons/VisibilityOff'
import { domainData } from '../domainData'
import { authorList, nameList } from '../../utils'
import EntryDetails from '../entry/EntryDetails'
import { EntryButton } from '../nav/Routes'
import { useApi, withApi } from '../api'

export function Published(props) {
  const {user} = useApi()
  const {entry} = props
  if (entry.published) {
    if (entry.with_embargo) {
      if (user && entry.uploader.user_id === user.sub) {
        if (entry.owners.length === 1) {
          return <Tooltip title="published with embargo by you and only accessible by you">
            <UploaderIcon color="error" />
          </Tooltip>
        } else {
          return <Tooltip title="published with embargo by you and only accessible to you and users you shared the data with">
            <SharedIcon color="error" />
          </Tooltip>
        }
      } else if (user && entry.owners.find(user => user.user_id === user.sub)) {
        return <Tooltip title="published with embargo and shared with you">
          <SharedIcon color="error" />
        </Tooltip>
      } else {
        if (user) {
          return <Tooltip title="published with embargo and not accessible by you">
            <PrivateIcon color="error" />
          </Tooltip>
        } else {
          return <Tooltip title="published with embargo and might become accessible after login">
            <PrivateIcon color="error" />
          </Tooltip>
        }
      }
    } else {
      return <Tooltip title="published and accessible by everyone">
        <PublicIcon color="primary" />
      </Tooltip>
    }
  } else {
    return <Tooltip title="you have not published this entry yet">
      <UploaderIcon color="error"/>
    </Tooltip>
  }
}

export class EntryListUnstyled extends React.Component {
  static propTypes = {
    classes: PropTypes.object.isRequired,
    data: PropTypes.object,
    query: PropTypes.object.isRequired,
    onChange: PropTypes.func,
    onEdit: PropTypes.func,
    history: PropTypes.any.isRequired,
    order_by: PropTypes.string.isRequired,
    order: PropTypes.number.isRequired,
    page: PropTypes.number.isRequired,
    per_page: PropTypes.number.isRequired,
    editable: PropTypes.bool,
    editUserMetadataDialogProps: PropTypes.object,
    columns: PropTypes.object,
    title: PropTypes.string,
    actions: PropTypes.element,
    showEntryActions: PropTypes.func,
    selectedColumns: PropTypes.arrayOf(PropTypes.string),
    domain: PropTypes.object,
    user: PropTypes.object,
    showAccessColumn: PropTypes.bool,
    entryPagePathPrefix: PropTypes.string,
    entryDetailsWidth: PropTypes.number
  }

  static styles = theme => ({
    root: {
      overflow: 'auto'
    },
    entryDetails: {
      paddingTop: theme.spacing(2),
      paddingLeft: theme.spacing(2),
      paddingRight: theme.spacing(2)
    },
    entryDetailsContents: {
      display: 'flex',
      maxWidth: 1024,
      margin: 'auto'
    },
    entryDetailsRow: {
      paddingRight: theme.spacing(2),
      width: '33%'
    },
    entryDetailsActions: {
      display: 'flex',
      flexBasis: 'auto',
      flexGrow: 0,
      flexShrink: 0,
      justifyContent: 'flex-end',
      marginBottom: theme.spacing(1),
      marginTop: theme.spacing(2)
    }
  })

  state = {
    selected: []
  }

  static defaultColumns = {
    mainfile: {
      label: 'Mainfile',
      render: entry => entry.mainfile,
      supportsSort: true,
      ellipsisFront: true,
      description: 'The mainfile of this entry within its upload.'
    },
    upload_time: {
      label: 'Upload time',
      render: entry => new Date(entry.upload_time).toLocaleString(),
      supportsSort: true,
      description: 'The time this entry was uploaded.'
    },
    authors: {
      label: 'Authors',
      render: entry => authorList(entry),
      supportsSort: true,
      description: 'The authors of this entry. This includes the uploader and its co-authors.'
    },
    owners: {
      label: 'Owner',
      render: entry => nameList(entry.owners || []),
      supportsSort: true,
      description: 'The uploader and everybody that this entry is shared with.'
    },
    // co_authors: {
    //   label: 'co-Authors',
    //   render: entry => nameList(entry.co_authors || []),
    //   supportsSort: false,
    //   description: 'The people that this entry was co authored with'
    // },
    // shared_with: {
    //   label: 'Shared with',
    //   render: entry => nameList(entry.shared_with || []),
    //   supportsSort: false,
    //   description: 'The people that this entry was shared with'
    // },
    uploader: {
      label: 'Uploader',
      render: entry => entry.uploader?.name || '',
      supportsSort: true,
      description: 'The uploader of this entry.'
    },
    comment: {
      label: 'Comment',
      render: entry => entry.comment,
      supportsSort: false,
      description: 'User provided comment on this entry'
    },
    references: {
      label: 'References',
      render: entry => {
        const refs = entry.references || []
        if (refs.length > 0) {
          return (
            <div style={{display: 'inline'}}>
              {refs.map((ref, i) => <span key={ref}>
                <Link href={ref}>{ref}</Link>{(i + 1) < refs.length ? ', ' : <React.Fragment/>}
              </span>)}
            </div>
          )
        } else {
          return <i>no references</i>
        }
      },
      supportsSort: true
    },
    datasets: {
      label: 'Datasets',
      render: entry => {
        const datasets = entry.datasets || []
        if (datasets.length > 0) {
          return datasets.map(dataset => dataset.name).join(', ')
        } else {
          return <i>no datasets</i>
        }
      },
      supportsSort: false,
      description: 'The dataset names that this entry belongs to.'
    },
    published: {
      label: 'Access',
      align: 'center',
      render: (entry) => <Published entry={entry} />
    }
  }

  // TODO was this really intentional
  UNSAFE_componentWillUpdate(prevProps) {
    if (prevProps.data !== this.props.data) {
      this.setState({selected: []})
    }
  }

  handleChange(changes) {
    if (this.props.onChange) {
      this.props.onChange(changes)
    }
  }

  handleClickCalc(calc) {
    const prefix = this.props.entryPagePathPrefix || ''
    const url = `${prefix}/entry/id/${calc.upload_id}/${calc.calc_id}`
    this.props.history.push(url)
  }

  handleChangePage = (event, page) => {
    this.handleChange({page: page + 1})
  }

  handleChangeRowsPerPage = event => {
    const rowsPerPage = event.target.value
    this.handleChange({per_page: rowsPerPage})
  }

  handleSort(columnKey) {
    if (this.props.order_by === columnKey) {
      this.handleChange({order: this.props.order * -1})
    } else {
      this.handleChange({order: 1, order_by: columnKey})
    }
  }

  renderEntryDetails(row) {
    const { classes } = this.props
    const domain = (row.domain && domainData[row.domain]) || domainData.dft

    return (<div className={classes.entryDetails} style={{width: this.props.entryDetailsWidth}}>
      <div className={classes.entryDetailsContents} >
        <div className={classes.entryDetailsRow}>
          <EntryDetails data={row} />
        </div>

        <div className={classes.entryDetailsRow}>
          <Quantity className={classes.entryDetailsRow} column>
            <Quantity quantity='comment' placeholder='no comment' data={row} />
            <Quantity quantity='references' placeholder='no references' data={row}>
              {row.references && <div style={{display: 'inline-grid'}}>
                {(row.references || []).map(ref => <Typography key={ref} noWrap>
                  <Link href={ref}>{ref}</Link>
                </Typography>)}
              </div>}
            </Quantity>
            <Quantity quantity='authors' data={row}>
              <Typography>
                {authorList(row)}
              </Typography>
            </Quantity>
            <Quantity quantity='datasets' placeholder='no datasets' data={row}>
              <div>
                {(row.datasets || []).map(ds => (
                  <Typography key={ds.dataset_id}>
                    <Link component={RouterLink} to={`/dataset/id/${ds.dataset_id}`}>{ds.name}</Link>
                    {ds.doi ? <span>&nbsp; (<Link href={`https://dx.doi.org/${ds.doi}`}>{ds.doi}</Link>)</span> : <React.Fragment/>}
                  </Typography>))}
              </div>
            </Quantity>
          </Quantity>
        </div>

        <div className={classes.entryDetailsRow} style={{paddingRight: 0}}>
          <Quantity column >
            {/* <Quantity quantity="pid" label='PID' placeholder="not yet assigned" noWrap data={row} withClipboard /> */}
            <Quantity quantity="calc_id" label={`${domain ? domain.entryLabel : 'entry'} id`} noWrap withClipboard data={row} />
            <Quantity quantity="raw_id" label={`raw id`} noWrap withClipboard data={row} />
            <Quantity quantity="external_id" label={`external id`} noWrap withClipboard data={row} />
            <Quantity quantity='mainfile' noWrap ellipsisFront data={row} withClipboard />
            <Quantity quantity="upload_id" label='upload id' data={row} noWrap withClipboard>
              <Typography style={{flexGrow: 1}}>
                <Link component={RouterLink} to={`/uploads/${row.upload_id}`}>{row.upload_id}</Link>
              </Typography>
            </Quantity>
          </Quantity>
        </div>
      </div>

      <div className={classes.entryDetailsActions}>
        {this.showEntryActions(row) &&
          <EntryButton color="primary" entryId={row.entry_id} uploadId={row.upload_id}>
            Show raw files and archive
          </EntryButton>
        }
      </div>
    </div>)
  }

  showEntryActions(row) {
    const { user } = this.props
    if (row.with_embargo && !(user && row.owners.find(owner => owner.user_id === user.sub))) {
      return false
    } else {
      return !this.props.showEntryActions || this.props.showEntryActions(row)
    }
  }

  renderEntryActions(row, selected) {
    if (this.showEntryActions(row)) {
      return <Tooltip title="Show raw files and archive">
        <EntryButton
          style={selected ? {color: 'white'} : null} component={IconButton}
          entryId={row.entry_id} uploadId={row.upload_id}
        >
          <DetailsIcon />
        </EntryButton>
      </Tooltip>
    } else {
      return ''
    }
  }

  render() {
    const { classes, data, order, order_by, page, per_page, domain, editable, title, query, actions, user, showAccessColumn, ...rest } = this.props
    const { selected } = this.state

    const results = data?.results || data?.data || []
    const total = data?.pagination.total
    const totalNumber = total || 0

    const columns = this.props.columns || {
      ...domain.searchResultColumns,
      ...EntryListUnstyled.defaultColumns
    }

    let selectedColumns = this.props.selectedColumns
    if (!selectedColumns) {
      selectedColumns = [...domain.defaultSearchResultColumns]
      if (user !== undefined || showAccessColumn) {
        selectedColumns.push('published')
      }
      selectedColumns.push('authors')
    }

    const pagination = <TablePagination
      rowsPerPageOptions={[5, 10, 25, 50, 100]}
      count={totalNumber}
      rowsPerPage={per_page}
      page={page - 1}
      onChangePage={this.handleChangePage}
      onChangeRowsPerPage={this.handleChangeRowsPerPage}
      labelDisplayedRows={({ from, to, count }) => `${from.toLocaleString()}-${to.toLocaleString()} of ${count.toLocaleString()}`}
    />

    const example = selected && selected.length > 0 ? results.find(d => d.calc_id === selected[0]) : results[0]
    const selectQuery = (selected && selected.length > 0) ? {calc_id: selected, owner: query['owner']} : query
    const createActions = (props, moreActions) => <React.Fragment>
      {example && editable ? <EditUserMetadataDialog
        example={example} total={selected === null ? totalNumber : selected.length}
        onEditComplete={() => this.props.onEdit()}
        {...props} {...(this.props.editUserMetadataDialogProps || {})}
      /> : ''}
      <DownloadButton
        tooltip="Download files"
        {...props}/>
      {moreActions}
    </React.Fragment>
    const selectActions = createActions({query: selectQuery, buttonProps: {color: 'secondary'}})
    const allActions = actions

    return (
      <div className={classes.root}>
        <DataTable
          entityLabels={domain ? [domain.entryLabel, domain.entryLabelPlural] : ['entry', 'entries']}
          selectActions={selectActions}
          id={row => row.entry_id}
          total={total}
          columns={columns}
          selectedColumns={selectedColumns}
          selectedColumnsKey="entries"
          entryDetails={this.renderEntryDetails.bind(this)}
          entryActions={this.renderEntryActions.bind(this)}
          data={results}
          order={order === 1 ? 'desc' : 'asc'}
          orderBy={order_by}
          selected={this.state.selected}
          onSelectionChanged={selection => this.setState({selected: selection})}
          onOrderChanged={(order, orderBy) => this.handleChange({order: order === 'asc' ? -1 : 1, order_by: orderBy})}
          rows={per_page}
          pagination={pagination}
          actions={allActions}
          {...rest}
        />
      </div>
    )
  }
}

const EntryList = withApi(compose(withRouter, withStyles(EntryListUnstyled.styles))(EntryListUnstyled))

export default EntryList
