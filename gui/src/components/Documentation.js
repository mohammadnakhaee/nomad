import React, { Component } from 'react'
import HtmlToReact from 'html-to-react'
import { withRouter } from 'react-router-dom';
import { HashLink as Link } from 'react-router-hash-link'
import './Documentation.css'
import Url from 'url-parse'

const processNodeDefinitions = new HtmlToReact.ProcessNodeDefinitions(React)
const processingInstructions = location => {
  return [
    {
      // We have to remove sphynx header links. Not all of them are cought with css.
      shouldProcessNode: node => node.name === 'a' && node.children[0].data === '¶',
      processNode: (node, children) => {
        return ''
      }
    },
    {
      // We have to replace the sphynx links with router Links;
      // the hrefs have to be processed to be compatible with router, i.e. they have
      // to start with /documentation/.
      shouldProcessNode: node => node.type === 'tag' && node.name === 'a' && node.attribs['href'] && !node.attribs['href'].startsWith('http'),
      processNode: (node, children) => {
        const linkUrl = Url(node.attribs['href'])
        let pathname = linkUrl.pathname.replace(/^\/documentation/, '').replace(/^\//, '')
        if (pathname === '' ) {
          pathname = location.pathname
        } else {
          pathname = `/documentation/${pathname}`
        }
        return (<Link smooth to={pathname + (linkUrl.hash || '#')}>{children}</Link>)
      }
    },
    {
      shouldProcessNode: node => true,
      processNode: processNodeDefinitions.processDefaultNode
    }
  ]
}
const isValidNode = () => true
const htmlToReactParser = new HtmlToReact.Parser();
const domParser = new DOMParser()

class Documentation extends Component {
  state = {
    react: ''
  }

  onRouteChanged() {
    const fetchAndUpdate = path => {
      fetch(`/docs/${path}`)
        .then(response => response.text())
        .then(content => {
          // extract body of html page
          const doc = domParser.parseFromString(content, "application/xml")
          const bodyHtml = doc.getElementsByTagName('body')[0].innerHTML

          // replace a hrefs with Link to
          const react = htmlToReactParser.parseWithInstructions(bodyHtml, isValidNode, processingInstructions(this.props.location))

          this.setState({
            react: react
          })
        })
        .catch(err => {
          if (path !== 'index.html') {
            fetchAndUpdate('index.html')
          } else {
            console.error(err)
          }
        })
    }
    const path = this.props.location.pathname.replace('/documentation/', '')
    fetchAndUpdate(path)
  }

  componentDidUpdate(prevProps) {
    if (this.props.location !== prevProps.location) {
      this.onRouteChanged()
    }
  }

  componentWillMount() {
    this.onRouteChanged()
  }

  render() {
    return (
      <div className="root">
        {this.state.react}
      </div>
    )
  }
}

export default withRouter(Documentation)