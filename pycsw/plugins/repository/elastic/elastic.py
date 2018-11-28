# -*- coding: iso-8859-15 -*-
# =================================================================
#
# Authors: Mike Metcalfe <mikejmets@gmail.com>
# Credit: Base on the pycsw hypermap plugin that was
#         written by Tom Kralidis <tomkralidis@gmail.com>
#         https://github.com/cga-harvard/Hypermap-Registry
#
# Copyright (c) 2015 Mike Metcalfe
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
import json
import requests
# from pycsw.core import util

LOGGER = logging.getLogger(__name__)


class ElasticSearchRepository(object):
    """
    Class to interact with underlying repository
    """
    def __init__(self, context, repo_filter=None):
        """
        Initialize repository
        """

        self.context = context
        self.filter = repo_filter
        self.fts = False
        self.label = 'ElasticSearch'
        self.local_ingest = True

        self.dbtype = 'elasticsearch'

        # generate core queryables db and obj bindings
        self.queryables = {}

        for tname in self.context.model['typenames']:
            for qname in self.context.model['typenames'][tname]['queryables']:
                self.queryables[qname] = {}
                items = self.context.model['typenames'][tname]['queryables'][qname].items()

                for qkey, qvalue in items:
                    self.queryables[qname][qkey] = qvalue

        # flatten all queryables
        # TODO smarter way of doing this
        self.queryables['_all'] = {}
        for qbl in self.queryables:
            self.queryables['_all'].update(self.queryables[qbl])
        self.queryables['_all'].update(self.context.md_core_model['mappings'])

        # Check if elastic service is up
        if not self.elastic_available(self.filter):
            raise Exception('ElasticSearch backend not available')

    def query_ids(self, ids):
        """
        Query by list of identifiers
        """

        query = {'metadata_json.identifier.identifier': ids}
        results = self._run_es_query(self.filter, query)

        return results[1]

    def query_domain(self, domain, typenames, domainquerytype='list', count=False):
        """
        Query by property domain values
        """

        # objects = self._get_repo_filter(Layer.objects)

        # if domainquerytype == 'range':
        #     return [tuple(objects.aggregate(Min(domain), Max(domain)).values())]
        # else:
        #     if count:
        #         return [(d[domain], d['%s__count' % domain])
        #                 for d in objects.values(domain).annotate(Count(domain))]
        #     else:
        #         return objects.values_list(domain).distinct()

    def query_source(self, source):
        """
        Query by source
        """
        # return self._get_repo_filter().filter(url=source)

    def query(self, constraint, sortby=None, typenames=None, maxrecords=10, startposition=0):
        """
        Query records from underlying repository
        """

        query = self._get_repo_filter(constraint, sortby, maxrecords, startposition)
        if maxrecords:
            # run the raw query and get total
            tmp_query = dict(query)
            tmp_query.pop('size')
            results = self._run_es_query(self.filter, tmp_query)
            record_set_size = int(results[0])

        results = self._run_es_query(self.filter, query)

        if maxrecords:
            # Adjust numberOfRecordsMatched
            results[0] = str(record_set_size)

        return results

    def _parse_spatial_search(self, where):
        field = 'wtf'
        value = 'wtf'
        if 'ogc:Filter' not in where:
            return field, value
        afilter = where['ogc:Filter']
        field = 'overlaps'
        print(str(afilter))
        if 'ogc:Not' in afilter:
            field = 'excludes'
            afilter = afilter['ogc:Not']
        if 'ogc:BBOX' not in afilter:
            return field, value
        bbox = afilter['ogc:BBOX']
        if 'ogc:PropertyName' not in bbox:
            return field, value
        if 'gml:Envelope' not in bbox:
            return field, value
        # property_name = bbox['ogc:PropertyName']
        envelope = bbox['gml:Envelope']
        lower = envelope['gml:lowerCorner'].split()
        upper = envelope['gml:upperCorner'].split()
        values = '{},{},{},{}'.format(upper[1], lower[0], lower[1], upper[0])
        print('Spatials: {} {}'.format(field, values))
        return field, values

    def _get_repo_filter(self, constraint=None, sortby=None, maxrecords=10, startposition=0):
        """
        Construct an ES query params from the pyCSW constraints
        """
        query = {}
        if constraint:
            if constraint.get('type') == 'filter':
                field = None
                values = constraint.get('values', None)
                if len(values) > 0:
                    value = values[0]
                    value = value.replace('%', '')

                where = constraint.get('where')
                print('where: {}'.format(where))
                if where.startswith('title'):
                    field = 'metadata_json.titles.title'
                elif where.startswith('keywords'):
                    field = 'metadata_json.subjects.subject'
                elif where.startswith('query_spatial'):
                    field, value = self._parse_spatial_search(constraint['_dict'])

                if field and value:
                    query = {field: value}
                else:
                    query = {'wtf': 'wtf'}
            elif constraint.get('type') == 'cql_text':
                # TODO
                pass

        # Reset startposition if below zero
        if startposition < 0:
            startposition = 0

        if startposition:
            print('startposition: {}'.format(startposition))
            query['start'] = startposition + 1

        if sortby:
            print('sortby: {}'.format(sortby))
            if sortby.get('propertyname', False):
                if sortby['propertyname'] == 'identifier':
                    query['sort'] = 'metadata_json.identifier.identifier'
                elif sortby['propertyname'] == 'title':
                    query['sort'] = 'metadata_json.titles.title'
                elif sortby['propertyname'] == 'keywords':
                    query['sort'] = 'metadata_json.subjects.subject.raw'
                elif sortby['propertyname'] == 'creator':
                    query['sort'] = 'metadata_json.creators.creatorName.raw'
                elif sortby['propertyname'] == 'date_modified':
                    query['sort'] = 'metadata_json.dates.date.lte'
                elif sortby['propertyname'] == 'publisher':
                    query['sort'] = 'metadata_json.publisher.raw'
                else:
                    query['sort'] = 'metadata_json.{}'.format(sortby['propertyname'])
                query['sortorder'] = sortby.get('order').lower()

        if maxrecords:
            print('maxrecords: {}'.format(maxrecords))
            query['size'] = maxrecords

        return query

    def _run_es_query(self, base_url, params):

        try:
            params['index'] = 'md_index_1'
            print(str(params))
            response = requests.post(url=base_url, params=params)
        except requests.exceptions.ConnectionError as e:
            LOGGER.error('ConnectError connecting to Elastic search backend: {}'.format(e))
            return ['0', []]
        except Exception as e:
            LOGGER.error('Elastic search backend error: {}'.format(e))
            return ['0', []]

        if response.status_code != 200:
            LOGGER.error('Request failed with return code: %s' % (
                response.status_code))
            return ['0', []]

        try:
            json_dict = json.loads(response.text)
        except Exception as e:
            LOGGER.error('Response is not valid json: {}'.format(e))
            return ['0', []]

        if not json_dict.get('success', False):
            LOGGER.error('Backend request was unsuccess')
            return ['0', []]
        if not json_dict.get('results', False):
            LOGGER.error('Backend returned no results')
            return ['0', []]

        results = self.transpose_records(json_dict['results'])
        return [str(len(results)), results]

    def elastic_available(self, url):
        try:
            response = requests.get(url="{}".format(url))
        except Exception as e:
            LOGGER.error('ConnectError connecting to ElasticSearch backend: {}'.format(e))
            return False
        if response.status_code != 200:
            LOGGER.error('Connecting to ElasticSearch backend failed with return code: %s' % (response.status_code))
            return False
        return True

    def transpose_records(self, records):
        results = []
        for record in records:
            try:
                results.append(
                    self.transpose_a_record(record['metadata_json']))
            except AttributeError as e:
                print('AttributeError: {}'.format(e))
                raise e

        return results

    def transpose_a_record(self, record):

        result = {
            'type': 'service',
            'wkt_geometry': None,
        }
        if record.get('identifier', False):
            result['identifier'] = record['identifier']['identifier']

        if False:  # record.get('resourceType', False):
            result['type'] = record.get('resourceType')

        lstTitles = record.get('titles', False)
        if lstTitles:
            primary_is_set = False
            for ttl in lstTitles:
                title = ttl.get('title')
                if title:
                    if not primary_is_set:
                        # Use the first title
                        result['title'] = title
                        primary_is_set = True
                    elif not result.get('alternateTitle'):
                        result['alternateTitle'] = title
                        break
        publisher = record.get('publisher', False)
        if publisher:
            result['publisher'] = publisher

        lstContributors = record.get('contributors', False)
        if lstContributors:
            for cbt in lstContributors:
                contributorName = cbt['contributorName']
                if contributorName:
                    result['contributor'] = contributorName
                    break

        lstCreators = record.get('creators', False)
        if lstCreators:
            for crt in lstCreators:
                creatorName = crt['creatorName']
                if creatorName:
                    result['creator'] = creatorName
                    break

        lstSubjects = record.get('subjects', False)
        if lstSubjects:
            keywords = []
            for sbj in lstSubjects:
                subject = sbj['subject']
                if subject:
                    # Add all subjects
                    keywords.append(subject)
            result['keywords'] = ','.join(keywords)

        dc_date = get_dc_date(record)
        if dc_date:
            result['date'] = dc_date

        lstRights = record.get('rights', False)
        if lstRights:
            rights = []
            for rgt in lstRights:
                rights.append(rgt['rights'])
            result['accessconstraints'] = ','.join(rights)

        lstDescriptions = record.get('description', False)
        if lstDescriptions:
            # descriptionType is empty but shows Abstract on the real xml
            for desc in lstDescriptions:
                if desc.get('descriptionType', '') in ['', 'abstract']:
                    result['abstract'] = desc['description']
                    break

        lstDates = record.get('dates', False)
        if lstDates:
            for adate in lstDates:
                if adate.get('dateType', '') in ['Updated']:
                    result['date_modified'] = adate['date']
                    break

        language = record.get('language', False)
        if language:
            result['language'] = language

        lstFormats = record.get('formats', False)
        if lstFormats:
            # Assume first is correct
            if lstFormats[0].get('format', False):
                result['format'] = lstFormats[0].get('format')

        asource = record.get('immutableResource', False)
        if asource:
            if asource.get('resourceURL', False):
                result['source'] = asource.get('resourceURL')

        lstGeoLocations = record.get('geoLocations', False)
        if lstGeoLocations:
            for loc in lstGeoLocations:
                if loc.get('geoLocationPolygons', False):
                    # Assume first is correct
                    result['wkt_geometry'] = loc['geoLocationPolygons'][0]
                    break

        # TODO OUSTANDING FIELDS
        # anytext

        dataset = type('', (object,), result)()
        print(str(dataset))
        return dataset


def get_dc_date(record):
    dates = record.get('dates', [])
    dc_date = None
    for adate in dates:
        if adate.get('dateType') and \
           adate.get('dateType') == 'Submitted' and \
           adate.get('date'):
            dc_date = adate.get('date')
            break

    if dc_date is None:
        year = record.get('publicationYear')
        if year:
            dc_date = year

    return dc_date
