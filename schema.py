from influxdb_client import InfluxDBClient
import os

client = InfluxDBClient(
    url="http://localhost:8086",
    token='PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ==',
    org="DATABRIDGE"
)

query_api = client.query_api()

# Get measurements
query = 'import "influxdata/influxdb/schema"\n\nschema.measurements(bucket: "databridge")'
result = query_api.query(query)
print("Measurements:", [record.values['_value'] for record in result[0].records])

# Get field keys
query = 'import "influxdata/influxdb/schema"\n\nschema.fieldKeys(bucket: "databridge")'
result = query_api.query(query)
print("Field Keys:", [record.values['_value'] for record in result[0].records])

# Get tag keys  
query = 'import "influxdata/influxdb/schema"\n\nschema.tagKeys(bucket: "databridge")'
result = query_api.query(query)
print("Tag Keys:", [record.values['_value'] for record in result[0].records])

# Sample data
query = 'from(bucket: "databridge") |> range(start: -1h) |> limit(n: 3)'
result = query_api.query(query)
print("Sample Data:")
for table in result:
    for record in table.records:
        print(f"Time: {record.get_time()}, Measurement: {record.get_measurement()}, Field: {record.get_field()}, Value: {record.get_value()}, Tags: {record.values}")
