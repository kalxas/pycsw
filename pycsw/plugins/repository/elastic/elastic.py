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
# ToDo:
# Sort by BoundingBox
# =================================================================

import logging
import json
import requests
import string
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
        self.filter = repo_filter.split(',')[0]
        #self.elastic_index = repo_filter.split(',')[1]
        self.elastic_indeces= repo_filter.split(',')[1:len(repo_filter)-1]
        
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
        for es_index in self.elastic_indeces:
            results = self._es_single_record_query(self.filter, query, es_index)
            if int(results[0]) > 0:
                break
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
        #query['organization'] = "Climate Systems Analysis Group"
        #query['match'] = "must_not"

        index_sizes = []
        total_records = 0
        for es_index in self.elastic_indeces:
            size = self._get_total_records(self.filter, es_index)
            index_sizes.append(size)
            total_records += size

        results = self._run_es_query(self.filter, query, index_sizes)

        # Adjust numberOfRecordsMatched:
        #  set to Total records found at search index
        if total_records:
            results[0] = str(total_records)
        else:
            print("Error: Could not set records matched to total at Index," \
                  " setting instead to records length returned from query")

            results[0] = str(results[0])

        return results

    def _parse_spatial_search(self, where):
        field = '-'
        value = '-'
        lst = where.split('POLYGON')
        if len(lst) != 2:
            return field, value
        right = lst[1]
        idx = right.find('))')
        if idx < 0:
            return field, value
        coords = right[2:idx].split(', ')
        top_left = coords[3].split(' ')
        bot_right = coords[1].split(' ')
        field = 'overlaps'
        if right.split(' ')[-1] == "'false'":
            field = 'excludes'
        values = '{} {} {} {}'.format(
            top_left[0], top_left[1], bot_right[0], bot_right[1])
        print('Spatials: {} {}'.format(field, values))
        return field, values

    def _convert_single_query(self, where, value):
        query = {}
        if 'like' in where:
            value = value.replace('%', '*')

        if where.startswith('title'):
            field = 'metadata_json.titles.title'
            query = {field: value}
        elif where.startswith('keywords'):
            field = 'metadata_json.subjects.subject'
            query = {field: value}
        elif where.startswith('query_spatial'):
            field, value = \
                self._parse_spatial_search(where)
            query = {field: value}
        elif where.startswith('anytext'):
            field = 'anytext'
            query = {field: value}

        return query

    def _convert_complex_query(self, where, values):
        query = {}
        if ' and ' in where:
            and_list = where.split(' and ')
            items = []
            idx = 0
            for item in and_list:
                if item.startswith('query_spatial'):
                    value = ''
                else:
                    value = values[idx]
                    idx += 1
                sub = self._convert_complex_query(item, [value])
                items.append(sub)

            if items:
                query = {'and': _construct_kv_string(items)}

        elif ' or ' in where:
            or_list = where.split(' or ')
            items = []
            idx = 0
            for item in or_list:
                if item.startswith('query_spatial'):
                    value = ''
                else:
                    value = values[idx]
                    idx += 1
                sub = self._convert_complex_query(item, [value])
                items.append(sub)

            if items:
                query = {'or': _construct_kv_string(items)}

        elif where.startswith('not'):
            items = []
            idx = 0
            not_clause = where.replace('not ', '')
            if not_clause.startswith('query_spatial'):
                value = ''
            else:
                value = values[idx]
                idx += 1
            sub = self. _convert_complex_query(not_clause, value)
            if sub:
                query = {'not': _construct_kv_string([sub])}
        else:
            value = None
            if len(values) > 0:
                value = values[0]
            query = self._convert_single_query(where, value)

        return query

    def _get_repo_filter(self, constraint=None, sortby=None, maxrecords=10, startposition=0):
        """
        Construct an ES query params from the pyCSW constraints
        """
        query = {}
        if constraint:
            if constraint.get('type') == 'filter':
                values = constraint.get('values', None)
                print('values: {}'.format(values))

                where = constraint.get('where')
                print('where: {}'.format(where))

                query = self._convert_complex_query(where, values)

                if not query:
                    query = {'-': '-'}

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
                elif sortby['propertyname'] == 'wkt_geometry':
                    query['sort'] = 'metadata_json.geoLocations'
                elif sortby['propertyname'] == 'date':
                    query['sort'] = 'metadata_json.publicationYear'
                else:
                    query['sort'] = 'metadata_json.{}'.format(sortby['propertyname'])
                query['sortorder'] = sortby.get('order').lower()

        if maxrecords:
            print('maxrecords: {}'.format(maxrecords))
            query['size'] = maxrecords

        return query

    def _run_es_query(self, base_url, params, index_sizes=[]):
        # {'start': 10, 'index': u'sans-1878-mims-parent-records-1', 'size': '10'}
        # TODO: the below index slicing for mulitple indexes only works for one or two indeces

        # set start to align with elastic search query
        if 'start' in params:
            params['start'] = params['start'] + 1

        indece_slices = []
        read_all = False
        #print("PARAMS {}".format(params))
        #print("INDEX SIZES {}".format(index_sizes))
        if (len(index_sizes) > 1) and ('start' in params) and ('size' in params):
            if int(params['start']) > index_sizes[0]:
                indece_slices.append(None)
                indece_slices.append((int(params['start']) - index_sizes[0], params['size']))
            elif int(params['start']) <= index_sizes[0]:
                ind_diff_1 = index_sizes[0] - int(params['start']) + 1
                if int(params['size']) <= ind_diff_1:
                    indece_slices.append((params['start'], params['size']))
                    indece_slices.append(None)
                elif int(params['size']) > ind_diff_1:
                    indece_slices.append((params['start'], ind_diff_1))
                    indece_slices.append((1, int(params['size']) - ind_diff_1))
        elif (len(index_sizes) > 1) and ('start' not in params) and ('size' in params):
            if int(params['size']) > index_sizes[0]:
                indece_slices.append((1, index_sizes[0]))
                indece_slices.append((1, int(params['size']) - index_sizes[0]))
            else:
                indece_slices.append((1, params['size']))
                indece_slices.append(None)
        else:
            read_all = True

        all_results = []
        i = 0
        for es_index in self.elastic_indeces:
            response = None
            try:
                params['index'] = es_index
                #print("indec slices {} at index {}".format(indece_slices,i))
                if indece_slices[i]:
                    params['start'] = indece_slices[i][0]
                    params['size'] = indece_slices[i][1]
                #params['organization'] = "Climate Systems Analysis Group"
                    print("es query params {} {}".format(str(params), es_index))
                    response = requests.post(url=base_url, params=params)
                elif read_all:
                    print("es query params {} {}".format(str(params), es_index))
                    response = requests.post(url=base_url, params=params)
                i = i + 1
            except requests.exceptions.ConnectionError as e:
                LOGGER.error('ConnectError connecting to Elastic search backend: {}'.format(e))
                return ['0', []]
            except Exception as e:
                LOGGER.error('Elastic search backend error: {}'.format(e))
                return ['0', []]

            if response:
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
                all_results = all_results + results
        return [str(len(all_results)), all_results]

    def _get_total_records(self, base_url, es_index, params={}):
        try:
            # TODO: below approach gets total records implictly by requesting all titles
            #       refactor when elastic-agent supports total records at index request
            #       set response size (# of records) to max allowable by elastic-agent (10000)
            #params['organization'] = "Climate Systems Analysis Group"
            #params['match'] = "must_not"
            params['index'] = es_index
            params['fields'] = 'metadata_json.titles.title'
            params['size'] = 10000
            response = requests.post(url=base_url, params=params)
        except requests.exceptions.ConnectionError as e:
            print('ConnectError connecting to Elastic search backend: {}'.format(e))
            raise
        except Exception as e:
            print('Elastic search backend error: {}'.format(e))
            raise

        total_records = 0
        if response.status_code != 200:
            error = 'Total records request failed with return code: %s' % (response.status_code)
            print(error)
            raise Exception(error)

        try:
            json_dict = json.loads(response.text)
            total_records = int(json_dict['result_length'])
        except Exception as e:
            error = 'Response is not valid json: {}'.format(e)
            LOGGER.error(error)
            raise Exception(error)
        return total_records

    def _es_single_record_query(self, base_url, params, es_index):
        response = None
        try:
            params['index'] = es_index
            print("es query params {} {}".format(str(params), es_index))
            response = requests.post(url=base_url, params=params)
        except requests.exceptions.ConnectionError as e:
            LOGGER.error('ConnectError connecting to Elastic search backend: {}'.format(e))
            return ['0', []]
        except Exception as e:
            LOGGER.error('Elastic search backend error: {}'.format(e))
            return ['0', []]

        if response:
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

        def lit_str(in_str):
            not_allowed = r"\x0e"
            out_str = in_str
            if not_allowed in "%r" % out_str:
                out_str = "%r" % out_str
            return out_str

        result = {
            'type': 'service',
            'wkt_geometry': None,
        }
        if record.get('identifier', False):
            result['identifier'] = record['identifier']['identifier']

        if record.get('fileIdentifier',False):
            result['file_identifier'] = record['fileIdentifier']

        if record.get('relatedIdentifiers', False):
            related_ids = record['relatedIdentifiers']
            rid_url = ''
            for rid in related_ids:
                # resolve to one related id for now, preferably a DOI
                rid_url = rid['relatedIdentifier']
                if rid['relatedIdentifierType'] == 'DOI':
                    break
            result['related_identifiers'] = rid_url

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
                        result['title'] = lit_str(title)
                        primary_is_set = True
                    elif not result.get('alternateTitle'):
                        result['alternateTitle'] = title
                        break
        publisher = record.get('publisher', False)
        if publisher:
            result['publisher'] = publisher

        lstContributors = record.get('contributors', False)
        if lstContributors:
            contributors = []
            for cbt in lstContributors:
                contributorName = cbt['name']
                if contributorName:
                    contributors.append(contributorName)
            result['contributor'] = ';'.join(contributors)

        lstCreators = record.get('creators', False)
        if lstCreators:
            creators = []
            for crt in lstCreators:
                creatorName = crt['name']
                if creatorName:
                    creators.append(creatorName)
            result['creator'] = ';'.join(creators)

        lstRespParties = record.get('responsibleParties', False)
        result['contributor'] = str(lstRespParties)

        lstSubjects = record.get('subjects', False)
        if lstSubjects:
            keywords = []
            for sbj in lstSubjects:
                subject = sbj['subject']
                if subject and subject != "Downloadable Data":
                    # Add all subjects
                    keywords.append(subject)
            result['keywords'] = ','.join(keywords)


        descr_keywords = record.get('descriptiveKeywords', False)
        if descr_keywords:            
            def get_keyword_type(k_type):
                ktype_mappings = {'theme':'project', 'place':'geographic-location','stratum':'instrument'}
                if k_type in ktype_mappings:
                    return ktype_mappings[k_type]
                else:
                    return None

            keywords = []
            for d_kword in descr_keywords:
                tmp_list = []
                kw_type = get_keyword_type(d_kword['keywordType'])
                if kw_type:
                    tmp_list.append(kw_type)
                tmp_list.append(d_kword['keyword'])
                d_keyword = ": ".join(tmp_list)
                keywords.append(d_keyword)
            dk_list = ','.join(keywords)
            result['keywords'] += ',' + dk_list

        topic_categories = record.get('topicCategories', False)
        if topic_categories:
            categories = []
            for t_cat in topic_categories:
                categories.append(t_cat)
            result['topicategory'] = ','.join(categories)

        dc_date = _get_dc_date(record)
        if dc_date:
            result['date'] = dc_date
            result['date_publication'] = dc_date
            result['date_modified'] = dc_date

        #lstRights = record.get('rightsList', False)
        #if lstRights:
        #    rights = []
        #    for rgt in lstRights:
        #        rights.append(rgt['rights'])
        #    result['accessconstraints'] = ','.join(rights)

        constraints = record.get('constraints', False)[0]
        if constraints:
            print(constraints)
            access_constraints = constraints['accessConstraints'][0]
            rights = constraints['rights']
            #rights_uri = constraints['rightsURI']
            result['accessconstraints'] = access_constraints
            result['conditionapplyingtoaccessanduse'] = rights

        lstDescriptions = record.get('descriptions', False)
        if lstDescriptions:
            for desc in lstDescriptions:
                if desc.get('descriptionType', '').lower() in ['', 'abstract']:
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
        if isinstance(lstFormats, list) and len(lstFormats):
            # Assume first is correct
            result['format'] = lstFormats[0][0]

        #asource = record.get('immutableResource', False)
        #if asource:
        #    if asource.get('resourceURL', False):
        #        result['source'] = asource.get('resourceURL')

        lstGeoLocations = record.get('geoLocations', False)
        if lstGeoLocations:
            #print(lstGeoLocations)
            for loc in lstGeoLocations:
                if loc.get('geoLocationBox', False):
                    # Assume first is correct
                    result['wkt_geometry'] = loc.get('geoLocationBox')
                    break


        extent = record.get('extent',False)
        if extent:
            start_time = extent['temporalElement']['startTime']
            end_time = extent['temporalElement']['endTime']
            result['time_begin'] = start_time
            result['time_end'] = end_time
            


        # "name,description,protocol,url[^,,,[^,,,]]"
        lstLinks = record.get('linkedResources', False)
        links = []
        if lstLinks:
            protocols_allowed = ['Query','Information','Download','Metadata']
            #links = []
            for link in lstLinks:
                name = "%r" % link.get('resourceDescription')
                description = name
                #protocol="%r" % link.get('linkedResourceType')
                protocol=link.get('linkedResourceType')
                url = link.get('resourceURL').replace(',',"%2c")
                if protocol in protocols_allowed:
                    name = name.replace(",","")
                    description = description.replace(",","")
                    links.append("{},{},{},{}".format(name,description,protocol,url))
                else:
                    print("Invalid protocol: {}".format(protocol))

        immutableR = record.get('immutableResource', False)
        if immutableR:
            url = immutableR.get('resourceURL').replace(',',"%2c")
            #if url != 'download link unavailable':
            name = immutableR.get('resourceName')
            description = name
            protocol= "html"
            #print("\n\n Adding {},{},{},{} \n\n".format(name,description,protocol,url))
            links.append("{},{},{},{}".format(name,description,protocol,url))
            #print("Adding {}".format(url))
  
        if lstLinks or immutableR:
            result['links'] = "^".join(links)

        lineage = record.get('lineageStatement', False)
        if lineage:
            result['lineage'] = lineage        

        # TODO OUSTANDING FIELDS
        dataset = type('', (object,), result)()
        #print(str(dataset))
        return dataset


def _get_dc_date(record):
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


def _construct_kv_string(params):
    result = []
    for param in params:
        for key, value in param.items():
            result.append("{}={}".format(key, value))
    return ','.join(result)
