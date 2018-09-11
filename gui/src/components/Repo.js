import React from 'react'
import PropTypes from 'prop-types'
import { withStyles } from '@material-ui/core/styles'
import Table from '@material-ui/core/Table'
import TableBody from '@material-ui/core/TableBody'
import TableCell from '@material-ui/core/TableCell'
import TablePagination from '@material-ui/core/TablePagination'
import TableRow from '@material-ui/core/TableRow'
import Paper from '@material-ui/core/Paper'
import api from '../api'
import CalcLinks from './CalcLinks'
import { TableHead, LinearProgress, FormControl, FormControlLabel, Checkbox, FormGroup, FormLabel, Typography, IconButton, MuiThemeProvider } from '@material-ui/core'
import Markdown from './Markdown'
import { compose } from 'recompose'
import { withErrors } from './errors'
import AnalyticsIcon from '@material-ui/icons/Settings'
import { analyticsTheme } from '../config'
import Link from 'react-router-dom/Link'
// import PeriodicTable from './PeriodicTable'

class Repo extends React.Component {
  static propTypes = {
    classes: PropTypes.object.isRequired,
    raiseError: PropTypes.func.isRequired
  }

  static styles = theme => ({
    root: {},
    data: {
      width: '100%',
      marginTop: theme.spacing.unit * 3,
      overflowX: 'scroll'
    },
    progressPlaceholder: {
      height: 5
    },
    summary: {
      textAlign: 'center',
      marginTop: theme.spacing.unit * 2
    },
    selectFormGroup: {
      paddingLeft: theme.spacing.unit * 3
    },
    selectLabel: {
      padding: theme.spacing.unit * 2
    }
  })

  static rowConfig = {
    chemical_composition_bulk_reduced: 'Formula',
    program_name: 'Code',
    program_basis_set_type: 'Basis set',
    system_type: 'System',
    crystal_system: 'Crystal',
    space_group_number: 'Space group',
    XC_functional_name: 'XT treatment'
  }

  state = {
    data: [],
    page: 1,
    rowsPerPage: 5,
    total: 0,
    loading: true,
    owner: 'all'
  }

  update(page, rowsPerPage, owner) {
    this.setState({loading: true})
    owner = owner || this.state.owner
    api.repoAll(page, rowsPerPage, owner).then(data => {
      const { pagination: { total, page, per_page }, results } = data
      this.setState({
        data: results,
        page: page,
        rowsPerPage:
        per_page,
        total: total,
        loading: false,
        owner: owner
      })
    }).catch(errors => {
      this.setState({data: [], total: 0, loading: false, owner: owner})
      this.props.raiseError(errors)
    })
  }

  componentDidMount() {
    const { page, rowsPerPage } = this.state
    this.update(page, rowsPerPage)
  }

  handleChangePage = (event, page) => {
    this.update(page + 1, this.state.rowsPerPage)
  }

  handleChangeRowsPerPage = event => {
    const rowsPerPage = event.target.value
    this.update(this.state.page, rowsPerPage)
  }

  handleOwnerChange(owner) {
    this.update(this.state.page, this.state.rowsPerPage, owner)
  }

  render() {
    const { classes } = this.props
    const { data, rowsPerPage, page, total, loading } = this.state
    const emptyRows = rowsPerPage - Math.min(rowsPerPage, total - (page - 1) * rowsPerPage)

    const ownerLabel = {
      all: 'All calculations',
      user: 'Your calculations',
      staging: 'Only calculations from your staging area'
    }
    return (
      <div className={classes.root}>
        <Markdown>{`
          ## The Repository – Raw Code Data
        `}</Markdown>
        {/* <PeriodicTable/> */}
        <FormControl>
          <FormLabel>Filter calculations and only show: </FormLabel>
          <FormGroup row>
            {['all', 'user', 'staging'].map(owner => (
              <FormControlLabel key={owner}
                control={
                  <Checkbox checked={this.state.owner === owner} onChange={() => this.handleOwnerChange(owner)} value="owner" />
                }
                label={ownerLabel[owner]}
              />
            ))}
          </FormGroup>
        </FormControl>

        <FormGroup className={classes.selectFormGroup} row>
          <FormLabel classes={{root: classes.selectLabel}} style={{flexGrow: 1}}>

          </FormLabel>
          <FormLabel classes={{root: classes.selectLabel}}>
            Analyse {total} calculations in an analytics notebook
          </FormLabel>
          <MuiThemeProvider theme={analyticsTheme}>
            <IconButton color="primary" component={Link} to={`/analytics`}>
              <AnalyticsIcon />
            </IconButton>
          </MuiThemeProvider>
        </FormGroup>

        <Paper className={classes.data}>
          {loading ? <LinearProgress variant="query" /> : <div className={classes.progressPlaceholder} />}
          <Table>
            <TableHead>
              <TableRow>
                {Object.values(Repo.rowConfig).map((name, index) => (
                  <TableCell padding="dense" key={index}>{name}</TableCell>
                ))}
                <TableCell/>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.map((calc, index) => (
                <TableRow hover tabIndex={-1} key={index}>
                  {Object.keys(Repo.rowConfig).map((key, rowIndex) => (
                    <TableCell padding="dense" key={rowIndex}>{calc[key]}</TableCell>
                  ))}
                  <TableCell padding="dense">
                    <CalcLinks uploadHash={calc.upload_hash} calcHash={calc.calc_hash} />
                  </TableCell>
                </TableRow>
              ))}
              {emptyRows > 0 && (
                <TableRow style={{ height: 57 * emptyRows }}>
                  <TableCell colSpan={6} />
                </TableRow>
              )}
              <TableRow>
                <TablePagination
                  count={total}
                  rowsPerPage={rowsPerPage}
                  page={page - 1}
                  backIconButtonProps={{
                    'aria-label': 'Previous Page'
                  }}
                  nextIconButtonProps={{
                    'aria-label': 'Next Page'
                  }}
                  onChangePage={this.handleChangePage}
                  onChangeRowsPerPage={this.handleChangeRowsPerPage}
                />
              </TableRow>
            </TableBody>
          </Table>
        </Paper>
      </div>
    )
  }
}

export default compose(withErrors, withStyles(Repo.styles))(Repo)
