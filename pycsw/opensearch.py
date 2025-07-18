# -*- coding: utf-8 -*-
# =================================================================
#
# Authors: Tom Kralidis <tomkralidis@gmail.com>
#          Angelos Tzotsos <tzotsos@gmail.com>
#
# Copyright (c) 2024 Tom Kralidis
# Copyright (c) 2015 Angelos Tzotsos
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

import logging

from pycsw.core import util
from pycsw.core.etree import etree

LOGGER = logging.getLogger(__name__)

QUERY_PARAMETERS = [
    'q',
    'bbox',
    'time',
    'start',
    'stop',
    'eo:parentidentifier',
    'eo:processinglevel',
    'eo:producttype',
    'eo:platform',
    'eo:instrument',
    'eo:sensortype',
    'eo:cloudcover',
    'eo:snowcover',
    'eo:spectralrange',
    'eo:bands',
    'eo:orbitnumber',
    'eo:orbitdirection',
    'eo:illuminationelevationangle'
]


class OpenSearch(object):
    """OpenSearch wrapper class"""

    def __init__(self, context):
        """initialize"""

        self.namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            'eo': 'http://a9.com/-/opensearch/extensions/eo/1.0/',
            'geo': 'http://a9.com/-/opensearch/extensions/geo/1.0/',
            'os': 'http://a9.com/-/spec/opensearch/1.1/',
            'time': 'http://a9.com/-/opensearch/extensions/time/1.0/',
#            'georss': 'http://www.georss.org/georss'
        }

        self.context = context
        self.context.namespaces.update(self.namespaces)
        self.context.keep_ns_prefixes.append('geo')
        self.context.keep_ns_prefixes.append('eo')
        self.context.keep_ns_prefixes.append('time')

    def response_csw2opensearch(self, element, cfg):
        """transform a CSW response into an OpenSearch response"""

        root_tag = etree.QName(element).localname
        if root_tag == 'ExceptionReport':
            return element

        LOGGER.debug('RESPONSE: %s', root_tag)
        try:
            version = element.xpath('//@version')[0]
        except Exception as err:
            version = '3.0.0'

        self.exml = element
        self.cfg = cfg
        self.bind_url = util.bind_url(self.cfg['server'].get('url'))
        if self.bind_url.endswith(('/opensearch', '/opensearch?')):
            self.bind_url = self.bind_url.replace('/opensearch', '/csw')

        if version == '2.0.2':
            return self._csw2_2_os()
        elif version == '3.0.0':
            return self._csw3_2_os()

    def _csw2_2_os(self):
        """CSW 2.0.2 Capabilities to OpenSearch Description"""

        operation_name = etree.QName(self.exml).localname
        if operation_name == 'GetRecordsResponse':

            startindex = int(self.exml.xpath('//@nextRecord')[0]) - int(
                        self.exml.xpath('//@numberOfRecordsReturned')[0])
            if startindex < 1:
                startindex = 1

            node = etree.Element(util.nspath_eval('atom:feed',
                       self.context.namespaces), nsmap=self.namespaces)
            etree.SubElement(node, util.nspath_eval('atom:id',
                       self.context.namespaces)).text = self.cfg['server'].get('url')
            etree.SubElement(node, util.nspath_eval('atom:title',
                       self.context.namespaces)).text = self.cfg['metadata']['identification']['title']
            #etree.SubElement(node, util.nspath_eval('atom:updated',
            #  self.context.namespaces)).text = self.exml.xpath('//@timestamp')[0]

            etree.SubElement(node, util.nspath_eval('os:totalResults',
                        self.context.namespaces)).text = self.exml.xpath(
                        '//@numberOfRecordsMatched')[0]
            etree.SubElement(node, util.nspath_eval('os:startIndex',
                        self.context.namespaces)).text = str(startindex)
            etree.SubElement(node, util.nspath_eval('os:itemsPerPage',
                        self.context.namespaces)).text = self.exml.xpath(
                        '//@numberOfRecordsReturned')[0]

            for rec in self.exml.xpath('//atom:entry',
                        namespaces=self.context.namespaces):
                LOGGER.debug('Adding Atom entry')
                node.append(rec)
            for rec in self.exml.xpath('//csw:Record|//csw:BriefRecord|//csw:SummaryRecord',
                        namespaces=self.context.namespaces):
                LOGGER.debug('Converting CSW Record to Atom entry')
                node.append(self.cswrecord2atom(rec))
        elif operation_name == 'Capabilities':
            node = etree.Element(util.nspath_eval('os:OpenSearchDescription', self.namespaces), nsmap=self.namespaces)
            etree.SubElement(node, util.nspath_eval('os:ShortName', self.namespaces)).text = self.exml.xpath('//ows:Title', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:LongName', self.namespaces)).text = self.exml.xpath('//ows:Title', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Description', self.namespaces)).text = self.exml.xpath('//ows:Abstract', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Tags', self.namespaces)).text = ' '.join(x.text for x in self.exml.xpath('//ows:Keyword', namespaces=self.context.namespaces))

            node1 = etree.SubElement(node, util.nspath_eval('os:Url', self.namespaces))
            node1.set('type', 'application/atom+xml')
            node1.set('method', 'get')

            kvps = {
                'mode': 'opensearch',
                'service': 'CSW',
                'version': '2.0.2',
                'request': 'GetRecords',
                'elementsetname': 'full',
                'typenames': 'csw:Record',
                'resulttype': 'results',
                'q': '{searchTerms?}',
                'bbox': '{geo:box?}',
                'time': '{time:start?}/{time:end?}',
                'start': '{time:start?}',
                'stop': '{time:end?}',
                'startposition': '{startIndex?}',
                'maxrecords': '{count?}',
                'eo:cloudCover': '{eo:cloudCover?}',
                'eo:instrument': '{eo:instrument?}',
                'eo:orbitDirection': '{eo:orbitDirection?}',
                'eo:orbitNumber': '{eo:orbitNumber?}',
                'eo:parentIdentifier': '{eo:parentIdentifier?}',
                'eo:platform': '{eo:platform?}',
                'eo:processingLevel': '{eo:processingLevel?}',
                'eo:productType': '{eo:productType?}',
                'eo:sensorType': '{eo:sensorType?}',
                'eo:snowCover': '{eo:snowCover?}',
                'eo:spectralRange': '{eo:spectralRange?}',
                'eo:illuminationElevationAngle': '{eo:illuminationElevationAngle?}'
            }

            node1.set('template', '%s%s' % (self.bind_url,
                '&'.join([f'{k}={v}' for k, v in kvps.items()]))
            )

            #node1.set('template', '%smode=opensearch&service=CSW&version=2.0.2&request=GetRecords&elementsetname=full&typenames=csw:Record&resulttype=results&q={searchTerms?}&bbox={geo:box?}&time={time:start?}/{time:end?}&start={time:start?}&stop={time:end?}&startposition={startIndex?}&maxrecords={count?}' % self.bind_url)

            node1 = etree.SubElement(node, util.nspath_eval('os:Image', self.namespaces))
            node1.set('type', 'image/vnd.microsoft.icon')
            node1.set('width', '16')
            node1.set('height', '16')
            node1.text = 'https://pycsw.org/img/favicon.ico'

            etree.SubElement(node, util.nspath_eval('os:Developer', self.namespaces)).text = self.exml.xpath('//ows:IndividualName', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Context', self.namespaces)).text = self.exml.xpath('//ows:ElectronicMailAddress', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Attribution', self.namespaces)).text = self.exml.xpath('//ows:ProviderName', namespaces=self.context.namespaces)[0].text
        elif operation_name == 'ExceptionReport':
            node = self.exml
        else:  # return Description document
            node = etree.Element(util.nspath_eval('os:Description', self.context.namespaces))

        return node

    def _csw3_2_os(self):
        """CSW 3.0.0 Capabilities to OpenSearch Description"""

        response_name = etree.QName(self.exml).localname
        if response_name == 'GetRecordsResponse':

            startindex = int(self.exml.xpath('//@nextRecord')[0]) - int(
                        self.exml.xpath('//@numberOfRecordsReturned')[0])
            if startindex < 1:
                startindex = 1

            node = etree.Element(util.nspath_eval('atom:feed',
                       self.context.namespaces), nsmap=self.namespaces)
            etree.SubElement(node, util.nspath_eval('atom:id',
                       self.context.namespaces)).text = self.cfg['server'].get('url')
            etree.SubElement(node, util.nspath_eval('atom:title',
                       self.context.namespaces)).text = self.cfg['metadata']['identification']['title']
            author = etree.SubElement(node, util.nspath_eval('atom:author', self.context.namespaces))
            etree.SubElement(author, util.nspath_eval('atom:name', self.context.namespaces)).text = self.cfg['metadata']['provider']['name']
            etree.SubElement(node, util.nspath_eval('atom:link',
                       self.context.namespaces), rel='search',
                           type='application/opensearchdescription+xml',
                           href='%smode=opensearch&service=CSW&version=3.0.0&request=GetCapabilities' % self.bind_url)

            etree.SubElement(node, util.nspath_eval('atom:updated',
                self.context.namespaces)).text = self.exml.xpath('//@timestamp')[0]

            etree.SubElement(node, util.nspath_eval('os:Query', self.context.namespaces), role='request')

            matched = sum(int(x) for x in self.exml.xpath('//@numberOfRecordsMatched'))

            etree.SubElement(node, util.nspath_eval('os:totalResults', self.context.namespaces)).text = str(matched)

            etree.SubElement(node, util.nspath_eval('os:startIndex',
                        self.context.namespaces)).text = str(startindex)

            returned = sum(int(x) for x in self.exml.xpath('//@numberOfRecordsReturned'))

            etree.SubElement(node, util.nspath_eval('os:itemsPerPage', self.context.namespaces)).text = str(returned)

            for rec in self.exml.xpath('//atom:entry', namespaces=self.context.namespaces):
                LOGGER.debug('Adding Atom entry')
                node.append(rec)

            for rec in self.exml.xpath('//csw30:Record|//csw30:BriefRecord|//csw30:SummaryRecord', namespaces=self.context.namespaces):
                LOGGER.debug('Converting CSW Record to Atom entry')
                node.append(self.cswrecord2atom(rec))

        elif response_name == 'Capabilities':
            node = etree.Element(util.nspath_eval('os:OpenSearchDescription', self.namespaces), nsmap=self.namespaces)
            etree.SubElement(node, util.nspath_eval('os:ShortName', self.namespaces)).text = self.exml.xpath('//ows20:Title', namespaces=self.context.namespaces)[0].text[:16]
            etree.SubElement(node, util.nspath_eval('os:LongName', self.namespaces)).text = self.exml.xpath('//ows20:Title', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Description', self.namespaces)).text = self.exml.xpath('//ows20:Abstract', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Tags', self.namespaces)).text = ' '.join(x.text for x in self.exml.xpath('//ows20:Keyword', namespaces=self.context.namespaces))

            # Requirement-022
            node1 = etree.SubElement(node, util.nspath_eval('os:Url', self.namespaces))
            node1.set('type', 'application/xml')

            kvps = {
                'service': 'CSW',
                'version': '3.0.0',
                'request': 'GetRecords',
                'elementsetname': 'full',
                'typenames': 'csw:Record',
                'outputformat': 'application/xml',
                'outputschema': 'http://www.opengis.net/cat/csw/3.0',
                'recordids': '{geo:uid?}',
                'q': '{searchTerms?}',
                'bbox': '{geo:box?}',
                'time': '{time:start?}/{time:end?}',
                'start': '{time:start?}',
                'stop': '{time:end?}',
                'startposition': '{startIndex?}',
                'maxrecords': '{count?}',
                'eo:cloudCover': '{eo:cloudCover?}',
                'eo:instrument': '{eo:instrument?}',
                'eo:orbitDirection': '{eo:orbitDirection?}',
                'eo:orbitNumber': '{eo:orbitNumber?}',
                'eo:parentIdentifier': '{eo:parentIdentifier?}',
                'eo:platform': '{eo:platform?}',
                'eo:processingLevel': '{eo:processingLevel?}',
                'eo:productType': '{eo:productType?}',
                'eo:sensorType': '{eo:sensorType?}',
                'eo:snowCover': '{eo:snowCover?}',
                'eo:spectralRange': '{eo:spectralRange?}',
                'eo:illuminationElevationAngle': '{eo:illuminationElevationAngle?}'
            }

            node1.set('template', '%s%s' % (self.bind_url,
                '&'.join(f'{k}={v}' for k, v in kvps.items())))

            # Requirement-023
            node1 = etree.SubElement(node, util.nspath_eval('os:Url', self.namespaces))
            node1.set('type', 'application/atom+xml')

            kvps['outputformat'] = r'application%2Fatom%2Bxml'
            kvps['mode'] = 'opensearch'

            node1.set('template', '%s%s' % (self.bind_url,
                '&'.join(f'{k}={v}' for k, v in kvps.items())))

            node1 = etree.SubElement(node, util.nspath_eval('os:Image', self.namespaces))
            node1.set('type', 'image/vnd.microsoft.icon')
            node1.set('width', '16')
            node1.set('height', '16')
            node1.text = 'https://pycsw.org/img/favicon.ico'

            os_query = etree.SubElement(node, util.nspath_eval('os:Query', self.namespaces), role='example', searchTerms='cat')

            etree.SubElement(node, util.nspath_eval('os:Developer', self.namespaces)).text = self.exml.xpath('//ows20:IndividualName', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Contact', self.namespaces)).text = self.exml.xpath('//ows20:ElectronicMailAddress', namespaces=self.context.namespaces)[0].text
            etree.SubElement(node, util.nspath_eval('os:Attribution', self.namespaces)).text = self.exml.xpath('//ows20:ProviderName', namespaces=self.context.namespaces)[0].text
        elif response_name == 'ExceptionReport':
            node = self.exml
        else:  # GetRecordById output
            node = etree.Element(util.nspath_eval('atom:feed',
                       self.context.namespaces), nsmap=self.namespaces)
            etree.SubElement(node, util.nspath_eval('atom:id',
                       self.context.namespaces)).text = self.cfg['server'].get('url')
            etree.SubElement(node, util.nspath_eval('atom:title',
                       self.context.namespaces)).text = self.cfg['metadata']['identification']['title']
            #etree.SubElement(node, util.nspath_eval('atom:updated',
            #  self.context.namespaces)).text = self.exml.xpath('//@timestamp')[0]

            etree.SubElement(node, util.nspath_eval('os:totalResults',
                        self.context.namespaces)).text = '1'
            etree.SubElement(node, util.nspath_eval('os:startIndex',
                        self.context.namespaces)).text = '1'
            etree.SubElement(node, util.nspath_eval('os:itemsPerPage',
                        self.context.namespaces)).text = '1'

            for rec in self.exml.xpath('//atom:entry', namespaces=self.context.namespaces):
                #node.append(rec)
                node = rec
        return node

    def cswrecord2atom(self, rec):
        entry = etree.Element(util.nspath_eval('atom:entry', self.namespaces))

        etree.SubElement(entry, util.nspath_eval('atom:id', self.context.namespaces)).text = rec.xpath('dc:identifier', namespaces=self.context.namespaces)[0].text
        etree.SubElement(entry, util.nspath_eval('dc:identifier', self.context.namespaces)).text = rec.xpath('dc:identifier', namespaces=self.context.namespaces)[0].text
        etree.SubElement(entry, util.nspath_eval('atom:title', self.context.namespaces)).text = rec.xpath('dc:title', namespaces=self.context.namespaces)[0].text

        dc_date = rec.xpath('dc:date', namespaces=self.context.namespaces)
        if dc_date:
            etree.SubElement(entry, util.nspath_eval('atom:updated', self.context.namespaces)).text = dc_date[0].text

        for s in rec.xpath('dc:subject', namespaces=self.context.namespaces):
            etree.SubElement(entry, util.nspath_eval('atom:category', self.context.namespaces), term=s.text)

        for d in rec.xpath('dct:references', namespaces=self.context.namespaces):
            link = etree.SubElement(entry, util.nspath_eval('atom:link', self.context.namespaces))
            link.attrib['href'] = d.text

            scheme = d.attrib.get('scheme')
            if scheme is not None:
                if scheme == 'enclosure':
                    link.attrib['rel'] = scheme
                    link.attrib['type'] = 'application/octet-stream'
                else:
                    link.attrib['type'] = scheme

        bbox = rec.xpath('ows:BoundingBox|ows20:BoundingBox', namespaces=self.context.namespaces)
        if bbox:
            where = etree.SubElement(entry, util.nspath_eval('georss:where', {'georss': 'http://www.georss.org/georss'}))
            envelope = etree.SubElement(where, util.nspath_eval('gml:Envelope', self.context.namespaces))
            envelope.attrib['srsName'] = bbox[0].attrib.get('crs')
            etree.SubElement(envelope, util.nspath_eval('gml:lowerCorner', self.context.namespaces)).text = bbox[0].xpath('ows:LowerCorner|ows20:LowerCorner', namespaces=self.context.namespaces)[0].text
            etree.SubElement(envelope, util.nspath_eval('gml:upperCorner', self.context.namespaces)).text = bbox[0].xpath('ows:UpperCorner|ows20:UpperCorner', namespaces=self.context.namespaces)[0].text

        return entry


def kvp2filterxml(kvp, context, profiles, fes_version='1.0'):
    ''' transform kvp to filter XML string '''

    bbox_element = None
    time_element = None
    anytext_elements = []
    query_temporal_by_iso = False
    start_stop_elements_only = False

    eo_parentidentifier_element = None
    eo_bands_element = None
    eo_cloudcover_element = None
    eo_instrument_element = None
    eo_orbitdirection_element = None
    eo_orbitnumber_element = None
    eo_platform_element = None
    eo_processinglevel_element = None
    eo_producttype_element = None
    eo_sensortype_element = None
    eo_snowcover_element = None
    eo_illuminationelevationangle_element = None

    if profiles is not None and 'plugins' in profiles and 'APISO' in profiles['plugins']:
        query_temporal_by_iso = True

    # Count parameters
    par_count = 0
    for p in ['q','bbox','time']:
        if p in kvp and kvp[p] != '':
            par_count += 1

    # Create root element for FilterXML
    root = etree.Element(util.nspath_eval('ogc:Filter', context.namespaces))

    # bbox to FilterXML
    if 'bbox' in kvp and kvp['bbox'] != '':
        LOGGER.debug('Detected bbox parameter')
        bbox_list = [x.strip() for x in kvp['bbox'].split(',')]
        bbox_element = etree.Element(util.nspath_eval('ogc:BBOX',
                    context.namespaces))
        el = etree.Element(util.nspath_eval('ogc:PropertyName',
                    context.namespaces))
        el.text = 'ows:BoundingBox'
        bbox_element.append(el)
        env = etree.Element(util.nspath_eval('gml:Envelope',
                    context.namespaces))
        el = etree.Element(util.nspath_eval('gml:lowerCorner',
                    context.namespaces))

        if len(bbox_list) == 5:  # add srsName
            LOGGER.debug('Found CRS')
            env.attrib['srsName'] = bbox_list[4]
        else:
            LOGGER.debug('Assuming 4326')
            env.attrib['srsName'] = 'urn:ogc:def:crs:OGC:1.3:CRS84'
            if not validate_4326(bbox_list):
                msg = '4326 coordinates out of range: %s' % bbox_list
                LOGGER.error(msg)
                raise RuntimeError(msg)

        try:
            el.text = "%s %s" % (bbox_list[0], bbox_list[1])
        except Exception as err:
            errortext = 'Exception: OpenSearch bbox not valid.\nError: %s.' % str(err)
            LOGGER.exception(errortext)
        env.append(el)
        el = etree.Element(util.nspath_eval('gml:upperCorner',
                    context.namespaces))
        try:
            el.text = "%s %s" % (bbox_list[2], bbox_list[3])
        except Exception as err:
            errortext = 'Exception: OpenSearch bbox not valid.\nError: %s.' % str(err)
            LOGGER.exception(errortext)
        env.append(el)
        bbox_element.append(env)

    # q to FilterXML
    if 'q' in kvp and kvp['q'] != '':
        LOGGER.debug('Detected q parameter')
        qvals = kvp['q'].split()
        LOGGER.debug(qvals)
        if len(qvals) > 1:
            par_count += 1
        for qval in qvals:
            LOGGER.debug('processing q token')
            anytext_element = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo',
                        context.namespaces))
            el = etree.Element(util.nspath_eval('ogc:PropertyName',
                        context.namespaces))
            el.text = 'csw:AnyText'
            anytext_element.append(el)
            el = etree.Element(util.nspath_eval('ogc:Literal',
                        context.namespaces))
            el.text = qval
            anytext_element.append(el)
            anytext_elements.append(anytext_element)

    if ('start' in kvp or 'stop' in kvp) and 'time' not in kvp:
        start_stop_elements_only = True
        LOGGER.debug('Detected start/stop in KVP')
        kvp['time'] = ''
        if 'start' in kvp and kvp['start'] != '':
            kvp['time'] = kvp['start'] + '/'
        if 'stop' in kvp and kvp['stop'] != '':
            if len(kvp['time']) > 0:
                kvp['time'] += kvp['stop']
            else:
                kvp['time'] = '/' + kvp['stop']
            LOGGER.debug(f'new KVP time: {kvp["time"]}')

    # time to FilterXML
    if 'time' in kvp and kvp['time'] != '':
        LOGGER.debug('Detected time parameter %s', kvp['time'])
        time_list = kvp['time'].split("/")

        LOGGER.debug('TIMELIST: %s', time_list) 

        if len(time_list) == 2:
            if '' not in time_list:  # both dates present
                LOGGER.debug('Both dates present')
                if query_temporal_by_iso:
                    LOGGER.debug('Querying by ISO data extent')
                    time_element = etree.Element(util.nspath_eval('ogc:And',
                                   context.namespaces))
    
                    begin_element = etree.Element(util.nspath_eval('ogc:PropertyIsGreaterThanOrEqualTo',
                                    context.namespaces))
                    etree.SubElement(begin_element, util.nspath_eval('ogc:PropertyName',
                                    context.namespaces)).text = 'apiso:TempExtent_begin'
                    etree.SubElement(begin_element, util.nspath_eval('ogc:Literal',
                                     context.namespaces)).text = time_list[0]
    
                    end_element = etree.Element(util.nspath_eval('ogc:PropertyIsLessThanOrEqualTo',
                                  context.namespaces))
                    etree.SubElement(end_element, util.nspath_eval('ogc:PropertyName',
                                     context.namespaces)).text = 'apiso:TempExtent_end'
                    etree.SubElement(end_element, util.nspath_eval('ogc:Literal',
                                     context.namespaces)).text = time_list[1]
    
                    time_element.append(begin_element)
                    time_element.append(end_element)

                else:
                    LOGGER.debug('Querying by DC date')
                    time_element = etree.Element(util.nspath_eval('ogc:PropertyIsBetween',
                                   context.namespaces))
                    el = etree.Element(util.nspath_eval('ogc:PropertyName',
                                       context.namespaces))
                    el.text = 'dc:date'
                    time_element.append(el)
                    el = etree.Element(util.nspath_eval('ogc:LowerBoundary',
                                       context.namespaces))
                    el2 = etree.Element(util.nspath_eval('ogc:Literal',
                                        context.namespaces))
                    el2.text = time_list[0]
                    el.append(el2)
                    time_element.append(el)
                    el = etree.Element(util.nspath_eval('ogc:UpperBoundary',
                                context.namespaces))
                    el2 = etree.Element(util.nspath_eval('ogc:Literal',
                                context.namespaces))
                    el2.text = time_list[1]
                    el.append(el2)
                    time_element.append(el)
    
            else:   # one is empty
                LOGGER.debug('Querying by open-ended date')
                if time_list == ['', '']:
                    par_count -= 1
                # One of two is empty
                elif time_list[1] == '':  # start datetime but no end datetime
                    time_element = etree.Element(util.nspath_eval('ogc:PropertyIsGreaterThanOrEqualTo',
                                context.namespaces))
                    el = etree.Element(util.nspath_eval('ogc:PropertyName',
                                context.namespaces))
                    if query_temporal_by_iso:
                        el.text = 'apiso:TempExtent_begin'
                    else:
                        el.text = 'dc:date'
                    time_element.append(el)
                    el = etree.Element(util.nspath_eval('ogc:Literal',
                                context.namespaces))
                    el.text = time_list[0]
                    time_element.append(el)
                else:  # end datetime but no start datetime
                    time_element = etree.Element(util.nspath_eval('ogc:PropertyIsLessThanOrEqualTo',
                                context.namespaces))
                    el = etree.Element(util.nspath_eval('ogc:PropertyName',
                                context.namespaces))
                    if query_temporal_by_iso:
                        el.text = 'apiso:TempExtent_end'
                    else:
                        el.text = 'dc:date'
                    time_element.append(el)
                    el = etree.Element(util.nspath_eval('ogc:Literal',
                                context.namespaces))
                    el.text = time_list[1]
                    time_element.append(el)
        elif ((len(time_list) == 1) and ('' not in time_list)):
            LOGGER.debug('Querying time instant via dc:date')
            # This is an equal request
            time_element = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo',
                        context.namespaces))
            el = etree.Element(util.nspath_eval('ogc:PropertyName',
                        context.namespaces))
            el.text = 'dc:date'
            time_element.append(el)
            el = etree.Element(util.nspath_eval('ogc:Literal',
                        context.namespaces))
            el.text = time_list[0]
            time_element.append(el)
        else:
            # Error
            errortext = 'Exception: OpenSearch time not valid: %s.' % str(kvp['time'])
            LOGGER.error(errortext)

    if time_element is not None and start_stop_elements_only:
        par_count += 1

    LOGGER.debug('Processing EO queryables')
    if not util.is_none_or_empty(kvp.get('eo:parentidentifier')):
        par_count += 1
        eo_parentidentifier_element = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo', context.namespaces))
        etree.SubElement(eo_parentidentifier_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:ParentIdentifier'
        etree.SubElement(eo_parentidentifier_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = kvp['eo:parentidentifier']

    if not util.is_none_or_empty(kvp.get('eo:producttype')):
        par_count += 1
        eo_producttype_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_producttype_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Subject'
        etree.SubElement(eo_producttype_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*eo:productType:%s*' % kvp['eo:producttype']

    if not util.is_none_or_empty(kvp.get('eo:platform')):
        par_count += 1
        eo_platform_element = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo', context.namespaces))
        etree.SubElement(eo_platform_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Platform'
        etree.SubElement(eo_platform_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = kvp['eo:platform']

    if not util.is_none_or_empty(kvp.get('eo:processinglevel')):
        par_count += 1
        eo_processinglevel_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_processinglevel_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Subject'
        etree.SubElement(eo_processinglevel_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*eo:processingLevel:%s*' % kvp['eo:processinglevel']

    if not util.is_none_or_empty(kvp.get('eo:instrument')):
        par_count += 1
        eo_instrument_element = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo', context.namespaces))
        etree.SubElement(eo_instrument_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Instrument'
        etree.SubElement(eo_instrument_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = kvp['eo:instrument']

    if not util.is_none_or_empty(kvp.get('eo:sensortype')):
        par_count += 1
        eo_sensortype_element = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo', context.namespaces))
        etree.SubElement(eo_sensortype_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:SensorType'
        etree.SubElement(eo_sensortype_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = kvp['eo:sensortype']

    if not util.is_none_or_empty(kvp.get('eo:cloudcover')):
        par_count += 1
        eo_cloudcover_element = evaluate_literal(context, 'apiso:CloudCover', kvp['eo:cloudcover'])

    if not util.is_none_or_empty(kvp.get('eo:snowcover')):
        par_count += 1
        eo_snowcover_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_snowcover_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Subject'
        etree.SubElement(eo_snowcover_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*eo:snowCover:%s*' % kvp['eo:snowcover']

    if not util.is_none_or_empty(kvp.get('eo:spectralrange')):
        par_count += 1
        eo_bands_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_bands_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Bands'
        etree.SubElement(eo_bands_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*%s*' % kvp['eo:spectralrange']

    if not util.is_none_or_empty(kvp.get('eo:illuminationelevationangle')):
        par_count += 1
        eo_illuminationelevationangle_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_illuminationelevationangle_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:IlluminationElevationAngle'
        etree.SubElement(eo_illuminationelevationangle_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*%s*' % kvp['eo:illuminationelevationangle']

    if not util.is_none_or_empty(kvp.get('eo:orbitnumber')):
        par_count += 1
        eo_orbitnumber_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_orbitnumber_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Subject'
        etree.SubElement(eo_orbitnumber_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*eo:orbitNumber:%s*' % kvp['eo:orbitnumber']

    if not util.is_none_or_empty(kvp.get('eo:orbitdirection')):
        par_count += 1
        eo_orbitdirection_element = etree.Element(util.nspath_eval('ogc:PropertyIsLike', context.namespaces),
            matchCase='false', wildCard='*', singleChar='?', escapeChar='\\')
        etree.SubElement(eo_orbitdirection_element,
           util.nspath_eval('ogc:PropertyName', context.namespaces)).text = 'apiso:Subject'
        etree.SubElement(eo_orbitdirection_element, util.nspath_eval(
            'ogc:Literal', context.namespaces)).text = '*eo:orbitDirection:%s*' % kvp['eo:orbitdirection']

    LOGGER.info('Query parameter count: %s', par_count)
    if par_count == 0:
        return ''
    elif par_count == 1:
        LOGGER.debug('Single predicate filter')
        # Only one OpenSearch parameter exists
        if 'bbox' in kvp and kvp['bbox'] != '':
            LOGGER.debug('Adding bbox')
            root.append(bbox_element)
        elif time_element is not None:
            LOGGER.debug('Adding time')
            root.append(time_element)
        elif anytext_elements:
            LOGGER.debug('Adding anytext')
            root.extend(anytext_elements)
    elif par_count > 1:
        LOGGER.debug('ogc:And query (%d predicates)', par_count)
        # Since more than 1 parameter, append the AND logical operator
        logical_and = etree.Element(util.nspath_eval('ogc:And',
                context.namespaces))
        if bbox_element is not None:
            logical_and.append(bbox_element)
        if time_element is not None:
            logical_and.append(time_element)
        if anytext_elements is not None:
            logical_and.extend(anytext_elements)
        root.append(logical_and)

    if par_count == 1:
        node_to_append = root
    elif par_count > 1:
        node_to_append = logical_and

    LOGGER.debug('Adding EO queryables')
    for eo_element in [eo_producttype_element, eo_platform_element, eo_instrument_element,
                       eo_sensortype_element, eo_cloudcover_element, eo_snowcover_element,
                       eo_bands_element, eo_orbitnumber_element, eo_orbitdirection_element,
                       eo_processinglevel_element, eo_parentidentifier_element, eo_illuminationelevationangle_element]:
        if eo_element is not None:
            node_to_append.append(eo_element)

    # Render etree to string XML
    filterstring = etree.tostring(root, encoding='unicode')
    if fes_version == '2.0':
        filterstring = filterstring.replace('PropertyName', 'ValueReference')\
                                   .replace('xmlns:ogc="http://www.opengis.net/ogc"', 'xmlns:fes20="http://www.opengis.net/fes/2.0"')\
                                   .replace('ogc:', 'fes20:')\
                                   .replace('xmlns:gml311="http://www.opengis.net/gml"', 'xmlns:gml32="http://www.opengis.net/gml/3.2"')\
                                   .replace('gml311:', 'gml32:')

    LOGGER.debug(filterstring)

    return filterstring


def evaluate_literal(context, pname, pvalue):
    """
    Transforms OpenSearch EO mathematical notation
    to OGC FES syntax

    :param pname: parameter name
    :param pvalue: parameter value

    :returns: lxml Element of predicate
    """

    LOGGER.debug(f'property name: {pname}')
    LOGGER.debug(f'property value: {pvalue}')

    if pvalue.startswith('{') and pvalue.endswith('}'):
        # {n1,n2,…} equals to field=n1 OR field=n2 OR …
        values = pvalue.lstrip('{').rstrip('}').split(',')
        el = etree.Element(util.nspath_eval('ogc:Or', context.namespaces))

        for value in values:
            el2 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsEqualTo', context.namespaces))
            etree.SubElement(el2, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
            etree.SubElement(el2, util.nspath_eval('ogc:Literal', context.namespaces)).text = value

    elif pvalue.startswith('[') and pvalue.endswith(']'):
        # [n1,n2] equal to n1 <= field <= n2
        values = pvalue.lstrip('[').rstrip(']').split(',')
        el = etree.Element(util.nspath_eval('ogc:And', context.namespaces))

        el2 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsLessThanOrEqualTo', context.namespaces))
        etree.SubElement(el2, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el2, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[0]

        el3 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsGreaterThanOrEqualTo', context.namespaces))
        etree.SubElement(el3, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el3, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[1]

    elif pvalue.startswith(']') and pvalue.endswith('['):
        # ]n1,n2[ equals to n1 < field < n2
        values = pvalue.lstrip(']').rstrip('[').split(',')
        el = etree.Element(util.nspath_eval('ogc:And', context.namespaces))

        el2 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsLessThan', context.namespaces))
        etree.SubElement(el2, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el2, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[0]

        el3 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsGreaterThan', context.namespaces))
        etree.SubElement(el3, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el3, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[1]

    elif pvalue.startswith('['):
        # [n1 equals to n1<= field
        el = etree.Element(util.nspath_eval('ogc:PropertyIsGreaterThanOrEqualTo', context.namespaces))
        etree.SubElement(el, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el, util.nspath_eval('ogc:Literal', context.namespaces)).text = pvalue.lstrip('[')

    elif pvalue.endswith(']'):
        # n2] equals to field <= n2
        el = etree.Element(util.nspath_eval('ogc:PropertyIsLessThanOrEqualTo', context.namespaces))
        etree.SubElement(el, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el, util.nspath_eval('ogc:Literal', context.namespaces)).text = pvalue.rstrip(']')

    elif pvalue.startswith('[') and pvalue.endswith('['):
        # [n1,n2[ equals to n1 <= field < n2
        values = pvalue.lstrip('[').rstrip('[').split(',')
        el = etree.Element(util.nspath_eval('ogc:And', context.namespaces))

        el2 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsLessThanOrEqualTo', context.namespaces))
        etree.SubElement(el2, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el2, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[0]

        el3 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsGreaterThan', context.namespaces))
        etree.SubElement(el3, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el3, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[1]

    elif pvalue.startswith(']') and pvalue.endswith(']'):
        # ]n1,n2] equal to n1 < field <= n2
        values = pvalue.lstrip(']').rstrip(']').split(',')
        el = etree.Element(util.nspath_eval('ogc:And', context.namespaces))

        el2 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsLessThan', context.namespaces))
        etree.SubElement(el2, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el2, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[0]

        el3 = etree.SubElement(el, util.nspath_eval('ogc:PropertyIsGreaterThanOrEqualTo', context.namespaces))
        etree.SubElement(el3, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el3, util.nspath_eval('ogc:Literal', context.namespaces)).text = values[1]

    elif pvalue.startswith(']'):
        # ]n1 equals to n1 < field
        el = etree.Element(util.nspath_eval('ogc:PropertyIsGreaterThan', context.namespaces))
        etree.SubElement(el, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el, util.nspath_eval('ogc:Literal', context.namespaces)).text = pvalue.lstrip(']')

    elif pvalue.endswith('['):
        # n2[ equals to field < n2
        el = etree.Element(util.nspath_eval('ogc:PropertyIsLessThan', context.namespaces))
        etree.SubElement(el, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el, util.nspath_eval('ogc:Literal', context.namespaces)).text = pvalue.rstrip('[')

    else:
        # n1 equal to field = n1
        el = etree.Element(util.nspath_eval('ogc:PropertyIsEqualTo', context.namespaces))
        etree.SubElement(el, util.nspath_eval('ogc:PropertyName', context.namespaces)).text = pname
        etree.SubElement(el, util.nspath_eval('ogc:Literal', context.namespaces)).text = pvalue

    return el

def validate_4326(bbox_list):
    """Helper function to validate 4326."""
    is_valid = False
    if ((-180.0 <= float(bbox_list[0]) <= 180.0) and
            (-90.0 <= float(bbox_list[1]) <= 90.0) and
            (-180.0 <= float(bbox_list[2]) <= 180.0) and
            (-90.0 <= float(bbox_list[3]) <= 90.0)):
        is_valid = True
    return is_valid
