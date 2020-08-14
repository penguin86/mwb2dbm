#!/usr/bin/env python3

'''
mysqlworkbench2pgmodeler - mwb2dbm

@author Gabriele Tozzi <gabriele@tozzi.eu>
@brief Converts a MySQL Workbench mwb model into a pgModeler DBM model
@descr This software is in a "works for me" state, far to be complete
@license GNU GPLv3
'''

import os
import re
import copy
import logging
import zipfile
import collections
import lxml.etree

import dbo


class InvalidFileFormatException(RuntimeError):
	pass


class Main:
	''' Convert from MySQL Workbench to pgModeler '''

	MWB_INNER_FILE = 'document.mwb.xml'

	# Positions (x,y) scale ratio
	POS_SCALE_X = 1.8
	POS_SCALE_Y = 1.2

	def __init__(self):
		self.log = logging.getLogger('main')

	def _addDomainNodes(self, parent, name, baseType, constraintName, constraintExpr):
		domainNode = lxml.etree.Element('domain', {
			'name': name,
			'not-null': 'false',
		})
		parent.append(domainNode)

		domainNode.append(lxml.etree.Element('schema', {
			'name': 'public',
		}))

		domainNode.append(lxml.etree.Element('role', {
			'name': 'postgres',
		}))

		domainNode.append(lxml.etree.Element('type', {
			'name': baseType,
			'length': '0',
		}))

		constraintNode = lxml.etree.Element('constraint', {
			'name': constraintName,
			'type': 'check',
		})
		domainNode.append(constraintNode)

		exprNode = lxml.etree.Element('expression')
		exprNode.text = constraintExpr
		constraintNode.append(exprNode)

	def createDbm(self, dbname, tables, diagram, prependTableNameInIdx=False):
		''' Creates a new DBM model from the given diagram
		@param dbname The database name
		@param tables List of Table objects
		@param diagram The diagram
		@param prependTableNameInIdx bool When true, prepend table name in indexes
		'''
		enumid = 1
		domains = set()
		relnodes = []

		tree = lxml.etree.ElementTree(lxml.etree.Element('dbmodel', {
			'pgmodeler-ver': "0.9.2",
			'last-position': "0,0",
			'last-zoom': "1",
			'max-obj-count': "4",
			'default-schema': "public",
			'default-owner': "postgres",
		}))
		root = tree.getroot()

		database = lxml.etree.Element('database', {
			'name': dbname,
			'is-template': "false",
			'allow-conns': "true",
		})
		root.append(database)

		schema = lxml.etree.Element('schema', {
			'name': "public",
			'layer': "0",
			'fill-color': "#e1e1e1",
			'sql-disabled': "true",
		})
		root.append(schema)

		# Create layers
		for layer in diagram.layers:
			firstTable = diagram.getFirstTableFigureForLayer(layer)
			color = dbo.Color(firstTable['color'])
			bcolor = copy.copy(color)
			bcolor.add(-40)

			# Create text box
			tnode = lxml.etree.Element('textbox', {
				'name': layer['name'],
				'layer': '0',
				'font-size': "9",
			})
			root.append(tnode)

			pnode = lxml.etree.Element('position', {
				'x': str(int(layer['left'] * self.POS_SCALE_X)),
				'y': str(int(layer['top'] * self.POS_SCALE_Y)),
			})
			tnode.append(pnode)

			cnode = lxml.etree.Element('comment')
			cnode.text = layer['name']
			tnode.append(cnode)

			# Create tag
			tnode = lxml.etree.Element('tag', {
				'name': layer['name'].lower(),
			})
			root.append(tnode)

			node = lxml.etree.Element('style', {
				'id': 'table-body',
				'colors': '#fcfcfc,#fcfcfc,#808080',
			})
			tnode.append(node)

			node = lxml.etree.Element('style', {
				'id': 'table-ext-body',
				'colors': '#fcfcfc,#fcfcfc,#808080',
			})
			tnode.append(node)

			node = lxml.etree.Element('style', {
				'id': 'table-name',
				'colors': '#000000',
			})
			tnode.append(node)

			node = lxml.etree.Element('style', {
				'id': 'table-schema-name',
				'colors': '#000000',
			})
			tnode.append(node)

			node = lxml.etree.Element('style', {
				'id': 'table-title',
				'colors': "{},{},{}".format(color, color, bcolor),
			})
			tnode.append(node)

			node = lxml.etree.Element('comment')
			node.text = layer['name']
			tnode.append(node)

		# Create custom domains for unsigned int types
		for it in ('smallint', 'integer', 'bigint'):
			dname = 'u' + it
			domains.add(dname)
			self._addDomainNodes(root, dname, it, 'gt0', 'VALUE >= 0')

		# Save fks for later
		fks = []

		# Create tables
		for table in tables:
			figure = diagram.getTableFigure(table)
			layer = diagram.getFigureLayer(figure)

			tnode = lxml.etree.Element('table', {
				'name': table['name'],
				'layer': '0',
				'collapse-mode': "2",
				'max-obj-count': "0",
			})

			snode = lxml.etree.Element('schema', {
				'name': 'public',
			})
			tnode.append(snode)

			rnode = lxml.etree.Element('role', {
				'name': 'postgres',
			})
			tnode.append(rnode)

			node = lxml.etree.Element('tag', {
				'name': layer['name'].lower(),
			})
			tnode.append(node)

			pnode = lxml.etree.Element('position', {
				'x': str(int((figure['left'] + layer['left']) * self.POS_SCALE_X)),
				'y': str(int((figure['top'] + layer['top']) * self.POS_SCALE_Y)),
			})
			tnode.append(pnode)

			#TODO:
			tabAI = table['nextAutoInc']

			# Custom column sorting
			customidxs = collections.OrderedDict([
				('column', collections.OrderedDict()),
				# Unused: leave constraints in default order
				#('constraint', collections.OrderedDict()),
			])
			nextcolidx = -1

			for col in table.columns:
				nextcolidx += 1

				# Ignore foreign key columns (will be autogenerated by the reference)
				if col.fk:
					customidxs['column'][nextcolidx] = col['name']
					#customidxs['constraint'][nextcolidx] = col.fk['name']
					continue

				colnode = lxml.etree.Element('column', {
					'name': col['name'],
				})
				tnode.append(colnode)

				attrs = {
					'length': '0',
				}

				#TODO
				#print(col)
				#print()
				ai = True if col['autoIncrement'] else False
				dv = col['defaultValue']
				dvn = col['defaultValueIsNull']
				flags = col['flags']
				nn = True if col['isNotNull'] else False
				length = col['length']
				precision = col['precision']
				scale = col['scale']

				if col.type.type in ('SMALLINT', 'JSON', 'DECIMAL', 'VARCHAR', 'BIGINT', 'DATE', 'CHAR'):
					type = col.type.type.lower()
				elif col.type.type == 'INT':
					type = 'integer'
				elif col.type.type == 'TINYINT':
					if isinstance(col.type, dbo.UserType) and col.type['name'] in ('UBOOL', 'BOOLEAN', 'BOOL'):
						type = 'boolean'
					else:
						type = 'smallint'
				elif col.type.type == 'FLOAT':
					type = 'real'
				elif col.type.type == 'DOUBLE':
					type = 'double precision'
				elif col.type.type in ('TIMESTAMP', 'DATETIME', 'TIMESTAMP_F', 'DATETIME_F'):
					type = 'timestamp with time zone'
					attrs['with-timezone'] = 'true'
				elif col.type.type == 'TIME':
					type = 'time with time zone'
					attrs['with-timezone'] = 'true'
				elif col.type.type == 'TINYTEXT':
					type = 'varchar'
					attrs['length'] = '255'
				elif col.type.type == 'TEXT':
					type = 'varchar'
					attrs['length'] = '65535'
				elif col.type.type == 'MEDIUMTEXT':
					type = 'varchar'
					attrs['length'] = '16777215'
				elif col.type.type == 'LONGTEXT':
					type = 'varchar'
					attrs['length'] = '4294967295'
				elif col.type.type == 'ENUM':
					type = 'enum_' + str(enumid)
					enumid += 1

					# Add an enum type node
					utypenode = lxml.etree.Element('usertype', {
						'name': type,
						'configuration': 'enumeration',
					})
					root.append(utypenode)

					utypenode.append(lxml.etree.Element('schema', {
						'name': 'public',
					}))
					utypenode.append(lxml.etree.Element('role', {
						'name': 'postgres',
					}))
					utypenode.append(lxml.etree.Element('enumeration', {
						#TODO: enum list
						'values': 'abc,def',
					}))

					type = 'public.' + type
				else:
					self.log.warn('Unknown type %s', col.type.type)
					type = 'smallint'

				# Apply not-null
				if nn:
					colnode.set('not-null', "true")

				# Apply auto-increment
				if ai:
					if type in ('smallint', 'integer', 'bigint'):
						colnode.set('identity-type', "ALWAYS")

				# Apply default value
				#TODO: ON UPDATE CURRENT TIMESTAMP
				if dv:
					assert not dvn

					# Convert 0/1 to FALSE/TRUE when col is boolean
					if dv == '1':
						if type == 'boolean':
							dv = 'TRUE'
					elif dv == '0':
						if type == 'boolean':
							dv = 'FALSE'
					elif dv in ('TRUE', 'FALSE', 'CURRENT_TIMESTAMP'):
						pass
					elif dv.startswith("'") and dv.endswith("'"):
						pass
					elif dv == 'CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP':
						#TODO
						dv = 'CURRENT_TIMESTAMP'
					else:
						self.log.warn('Unknown default value %s', dv)
					colnode.set('default-value', dv)
				elif dvn:
					self.log.warn('Unsupported Null default value %s', dv)

				# Apply length/precision/scale
				if length > 0:
					assert precision < 0 and scale < 0, (length,precision,scale)
					assert attrs['length'] == '0'

					attrs['length'] = str(length)
				elif precision > 0:
					assert length < 0, (length,precision,scale)

					if scale < 0:
						# Since precision is not supported in pgSQL, create a domain for it

						dname = type + str(precision)
						if 'UNSIGNED' in flags:
							dname = 'u' + dname
						if dname not in domains:
							if 'UNSIGNED' in flags:
								minVal = 0
							else:
								minVal = '-' + '9' * precision
							maxVal = '9' * precision
							self._addDomainNodes(root, dname, type, 'range' + str(precision),
									'VALUE >= {} AND VALUE <= {}'.format(minVal, maxVal))
							domains.add(dname)
						type = 'public.' + dname
						flags.remove('UNSIGNED')
					else:
						assert attrs['length'] == '0'
						attrs['length'] = str(precision)
						attrs['precision'] = str(scale)

				elif scale > 0:
					assert False, (length,precision,scale)

				# Apply flags
				if flags:
					for flag in flags:
						if flag == 'UNSIGNED':
							if type in ('smallint', 'integer', 'bigint'):
								if ai:
									self.log.info('Unsupported domain in indentity column "%s.%s"',
											table['name'], col['name'])
								else:
									# Unsigned is not supported in PGSQL, so use a special domain
									type = 'public.u' + type
							else:
								self.log.error('Unsupported unsigned flag on %s field', type)
						else:
							self.log.warn('Unsupported flag: %s', flag)

				# TODO: integer/text precision
				# TODO: default
				# TODO: attribs
				# TODO: alias

				typenode = lxml.etree.Element('type', {
					'name': type,
				})
				for k, v in attrs.items():
					typenode.set(k, v)
				colnode.append(typenode)

				if 'comment' in col:
					commentnode = lxml.etree.Element('comment')
					commentnode.text = col['comment']
					colnode.append(commentnode)

			# Append at the end since enums must go above
			root.append(tnode)

			# Append indices and primary key
			for index in table.indices:
				# Filter out columns which are part of a FK (relation autogenerates the index)
				icols = [c for c in index.columns if not c.tableCol.fk]

				if not icols:
					continue

				if index['indexType'] == dbo.Index.TYPE_PRIMARY:
					# Only create the constraint, no need to create an index since PKs are implicitly indexed
					constraintnode = lxml.etree.Element('constraint', {
						'name': table['name'] + '_pk',
						'type': 'pk-constr',
						'table': 'public.' + table['name'],
					})
					constraintnode.append(lxml.etree.Element('columns', {
						'names': ','.join([c.tableCol['name'] for c in icols if not c.tableCol.fk]),
						'ref-type': 'src-columns',
					}))
					tnode.append(constraintnode)
				elif index['indexType'] in (dbo.Index.TYPE_UNIQUE, dbo.Index.TYPE_INDEX):
					# Create an index; index goes after the table
					prefix = table['name'] + '_' if prependTableNameInIdx else ''
					indexnode = lxml.etree.Element('index', {
						'name': prefix + index['name'],
						'table': 'public.' + table['name'],
						'concurrent': 'false',
						'unique': 'true' if index['unique'] else 'false',
						'fast-update': 'false',
						'buffering': 'false',
						'index-type': 'btree',
						'factor': '0',
					})
					root.append(indexnode)
					for icol in icols:
						idxelnode = lxml.etree.Element('idxelement', {
							'use-sorting': 'true',
							'nulls-first': 'false',
							'asc-order': 'false' if icol['descend'] else 'true',
						})
						indexnode.append(idxelnode)
						idxelnode.append(lxml.etree.Element('column', {
							'name': icol.tableCol['name'],
						}))
				else:
					raise NotImplementedError(index['indexType'])

			# Append foreign keys to the fk process list
			for fk in table.fks:
				fks.append(fk)

			# Append column order (customidx)
			for type, obj in customidxs.items():
				idxnode = lxml.etree.Element('customidxs', {
					'object-type': type,
				})

				if len(obj):
					tnode.append(idxnode)

				for idx, name in obj.items():
					idxnode.append(lxml.etree.Element('object', {
						'name': name,
						'index': str(idx),
					}))

		# Append relation nodes at the end, so all tables have been created now
		# process PKs earlier
		for fk in sorted(fks, key=lambda x: x.primary, reverse=True):
			if 'referencedTable' not in fk:
				# Apparently some fks are just indexes, ignore them
				continue

			if not fk['many']:
				raise NotImplementedError(fk)

			for rtable in tables:
				if rtable.id == fk['referencedTable']:
					break
			else:
				assert False, fk

			if len(fk.columns) != 1:
				raise NotImplementedError(fk)
			scol = fk.columns[0]

			relnode = lxml.etree.Element('relationship', {
				'name': fk['name'],
				'type': "rel1n",
				'layer': "0",
				'src-col-pattern': scol['name'],
				'pk-pattern': "{dt}_pk",
				'uq-pattern': "{dt}_uq",
				'src-fk-pattern': "{st}_fk",
				'src-table': "public." + rtable['name'],
				'dst-table': "public." + fk.table['name'],
				'src-required': "true" if fk['mandatory'] else "false",
				'dst-required': "false",
				'identifier': "true" if fk.primary else "false",
			})
			lnode = lxml.etree.Element('label', {
				'ref-type': "name-label",
			})
			relnode.append(lnode)
			lnode.append(lxml.etree.Element('position', {
				'x': "0",
				'y': "0",
			}))
			root.append(relnode)

		return tree

	def convert(self, mwbPath):
		''' Perform the conversion

		@param mwbPath string: The source file path
		'''

		# Extract XML from zip
		with zipfile.ZipFile(mwbPath, 'r') as mwbFile:
			if self.MWB_INNER_FILE not in mwbFile.namelist():
				raise InvalidFileFormatException(self.MWB_INNER_FILE + ' not found')

			with mwbFile.open(self.MWB_INNER_FILE) as xmlFile:
				tree = lxml.etree.parse(xmlFile)

		root = tree.getroot()

		# Basic XML validation
		if root.get('grt_format') != '2.0':
			raise InvalidFileFormatException(str(root.attrib))
		if root.get('document_type') != 'MySQL Workbench Model':
			raise InvalidFileFormatException(str(root.attrib))

		#for f in root.findall(".//value[@id='f1390fb2-1434-11e7-b731-10bf48baca66']"):
		#	print(tree.getelementpath(f))
		#raise RuntimeError()

		# Retrieve the document element
		document = root[0]
		assert document.tag == 'value', document.tag
		assert document.get('struct-name') == 'workbench.Document', document.attrib

		# Rietrieve the physical model element
		# TODO: support multiple models
		# Childs:
		#value {'type': 'object', 'struct-name': 'workbench.logical.Model', 'id': '4cd05de8-5bd6-11e1-bc3b-e0cb4ec5d89b', 'struct-checksum': '0xf4220370', 'key': 'logicalModel'}
		#value {'_ptr_': '0x5589fd96ef40', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'workbench.OverviewPanel', 'key': 'overviewPanels'}
		#value {'_ptr_': '0x5589fd972b10', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'workbench.physical.Model', 'key': 'physicalModels'}
		#value {'_ptr_': '0x558a018537d0', 'type': 'dict', 'key': 'customData'}
		#value {'type': 'object', 'struct-name': 'app.DocumentInfo', 'id': '4cd02f44-5bd6-11e1-bc3b-e0cb4ec5d89b', 'struct-checksum': '0xbba780b8', 'key': 'info'}
		#value {'type': 'object', 'struct-name': 'app.PageSettings', 'id': '4cd02bc0-5bd6-11e1-bc3b-e0cb4ec5d89b', 'struct-checksum': '0x7dc77977', 'key': 'pageSettings'}
		#value {'type': 'string', 'key': 'name'}
		models = document.findall("./value[@key='physicalModels']/value[@struct-name='workbench.physical.Model']")
		assert models, list(document)
		assert len(models) == 1, list(models)

		dbmTree = self.convertModel(models[0])

		# Determine detsination file name and save it
		root, ext = os.path.splitext(mwbPath)
		dbmPath = root + '.dbm'
		print('Saving converted file as ', dbmPath)

		with open(dbmPath, 'wb') as out:
			out.write(lxml.etree.tostring(dbmTree, pretty_print=True, xml_declaration=True, encoding='UTF-8'))

	def convertModel(self, model):
		#value {'type': 'object', 'struct-name': 'db.mysql.Catalog', 'id': '4cd06db0-5bd6-11e1-bc3b-e0cb4ec5d89b', 'struct-checksum': '0x82ad3466', 'key': 'catalog'}
		#value {'type': 'string', 'key': 'connectionNotation'}
		#value {'_ptr_': '0x558a018542b0', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'db.mgmt.Connection', 'key': 'connections'}
		#value {'_ptr_': '0x558a01854130', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'workbench.physical.Diagram', 'key': 'diagrams'}
		#value {'type': 'string', 'key': 'figureNotation'}
		#value {'_ptr_': '0x558a01854320', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'GrtStoredNote', 'key': 'notes'}
		#link {'type': 'object', 'struct-name': 'db.mgmt.Rdbms', 'key': 'rdbms'}
		#value {'_ptr_': '0x558a01854390', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'db.Script', 'key': 'scripts'}
		#value {'_ptr_': '0x558a01854400', 'type': 'dict', 'key': 'syncProfiles'}
		#value {'_ptr_': '0x558a01854480', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'GrtObject', 'key': 'tagCategories'}
		#value {'_ptr_': '0x558a018544f0', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'meta.Tag', 'key': 'tags'}
		#link {'type': 'object', 'struct-name': 'model.Diagram', 'key': 'currentDiagram'}
		#value {'_ptr_': '0x558a018540b0', 'type': 'dict', 'key': 'customData'}
		#value {'_ptr_': '0x558a018541a0', 'type': 'list', 'content-type': 'object', 'content-struct-name': 'model.Marker', 'key': 'markers'}
		#value {'_ptr_': '0x558a01854210', 'type': 'dict', 'key': 'options'}
		#value {'type': 'string', 'key': 'name'}
		#link {'type': 'object', 'struct-name': 'GrtObject', 'key': 'owner'}

		catalog = model.find("./value[@key='catalog']")
		assert catalog is not None, list(model)

		schema = catalog.find("./value[@key='schemata']/value[@struct-name='db.mysql.Schema']")
		assert schema is not None, list(catalog)

		schemaNameTag = schema.find("./value[@key='name']")
		schemaName = schemaNameTag.text

		simpleTypesTag = catalog.find("./value[@key='simpleDatatypes']")
		assert simpleTypesTag is not None, list(catalog)

		userTypesTag = catalog.find("./value[@key='userDatatypes']")
		assert userTypesTag is not None, list(catalog)

		types = {}
		for st in simpleTypesTag:
			t = dbo.SimpleType(st)
			assert t.id not in types
			types[t.id] = t
		for ut in userTypesTag:
			t = dbo.UserType(ut)
			assert t.id not in types
			types[t.id] = t

		tables = schema.find("./value[@key='tables']")
		assert len(tables), list(schema)

		convTables = []
		for table in tables:
			convTables.append(dbo.Table(table, types))

		diagrams = model.find("./value[@key='diagrams']")
		assert len(diagrams), list(schema)

		convDiagrams = []
		for diagram in diagrams:
			assert diagram.get('struct-name') == 'workbench.physical.Diagram'
			convDiagrams.append(dbo.Diagram(diagram))

		#TODO: multiple diagrams not supported, choose diagram
		self.log.info('Using diagram "%s"', convDiagrams[0]['name'])
		return self.createDbm(schemaName, convTables, convDiagrams[0],
				prependTableNameInIdx=True)


if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser(description='Convert a schema from MySQL Workbench to pgModeler format')
	parser.add_argument('mwb', help='the mwb source')

	args = parser.parse_args()

	logging.basicConfig(level=logging.DEBUG)

	Main().convert(args.mwb)
