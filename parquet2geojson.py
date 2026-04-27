import geopandas as gpd

# 1. Parquet 읽기
df = gpd.read_parquet('dist/markermap/emd_20260401.parquet')

# 2. GeoJSON으로 저장 (UTF-8 인코딩 기본 지원)
df.to_file('data.json', driver='GeoJSON')