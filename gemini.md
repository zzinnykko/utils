아하, 미묘하게 어긋났던 부분을 명확히 잡아주셔서 감사합니다!

원하시는 것은 **"동적 타일링(PMTiles 등)이나 서버 변환 없이, 브라우저에서 직접 3개의 Parquet 파일을 로드하여 행정구역 레벨별로 선 굵기를 다르게 렌더링하고, 그 위에 나중에 불러올 API 좌표를 아이콘으로 얹는 것"**이군요.

이 요구사항을 완벽하게 충족하려면 **`DuckDB-Wasm` (데이터 처리)**과 **`MapLibre GL JS` (지도 렌더링)** 조합이 최적입니다.

* **이유**: Leaflet은 이 정도 용량의 Parquet를 브라우저에서 직접 다루기에 퍼포먼스가 너무 낮고, Deck.gl은 3개 레이어의 선 두께 미세 조절과 API 좌표 추가를 실시간으로 제어하기에 코드가 다소 복잡해질 수 있습니다.

**MapLibre GL JS**는 벡터 엔진이라 GPU를 사용하여 수만 개의 읍면동 다각형도 선 두께별로 부드럽게 그려내며, API 좌표를 추가할 때 전용 Marker 기능이나 GeoJSON 소스 업데이트를 통해 가장 깔끔하게 처리할 수 있습니다.

---

### 구현 솔루션: DuckDB-Wasm + MapLibre GL JS

이 솔루션은 브라우저에서 SQL(DuckDB)로 Parquet 데이터를 필요한 포맷(GeoJSON)으로 즉석에서 변환하고, MapLibre GL JS의 스타일 함수를 이용해 선 굵기를 제어합니다.

#### 1. 필수 라이브러리 (CDN)

HTML `<head>`에 다음 라이브러리들을 추가하세요.

```html
<script src="https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@latest/dist/duckdb-browser.min.js"></script>

<link href="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.js"></script>
```

#### 2. 핵심 구현 코드 (Full HTML 예시)

`type="module"`을 사용하여 구현합니다. 이 코드는 인터넷이 연결된 환경에서 즉시 실행 가능하도록 CDN 주소를 사용합니다.

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>Parquet 행정구역 & API 마커 예제</title>
    <link href="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.css" rel="stylesheet" />
    <style>
        #map { position: absolute; top: 0; bottom: 0; width: 100%; }
        body { margin: 0; padding: 0; }
    </style>
</head>
<body>

<div id="map"></div>

<script src="https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@latest/dist/duckdb-browser.min.js"></script>

<script type="module">
    // MapLibre GL JS 가져오기
    import maplibregl from 'https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl-es.js';

    // 배경 지도 스타일 (무료)
    const baseStyle = 'https://demotiles.maplibre.org/style.json';

    async function initMap() {
        // 1. DuckDB 및 지도 초기화
        const db = await duckdb.createInstance();
        const conn = await db.connect();

        const map = new maplibregl.Map({
            container: 'map',
            style: baseStyle, // 배경 지도 타일
            center: [127.76, 35.90], // 대한민국 중심
            zoom: 6.5
        });

        // 2. Parquet 데이터 로드 함수 (SQL 활용)
        async function loadAndConvertParquet(fileName, tableName) {
            // Parquet 파일을 DuckDB에 가상 파일로 등록 (네트워크를 통해 읽음)
            await db.registerFileURL(fileName, `./${fileName}`, duckdb.DuckDBDataProtocol.HTTP, false);
            
            // SQL 쿼리로 데이터를 GeoJSON JSON 객체로 가져오기
            // 'geom' 컬럼은 이미 GeoParquet 형식으로 저장되어 있다고 가정합니다.
            const result = await conn.query(`SELECT CAST(ST_AsGeoJSON(geom) AS JSON) as geometry, properties FROM '${fileName}'`);
            
            // DuckDB 결과를 GeoJSON FeatureCollection 형태로 변환
            return {
                type: 'FeatureCollection',
                features: result.toArray().map(row => ({
                    type: 'Feature',
                    geometry: row.toJSON().geometry,
                    properties: row.toJSON().properties
                }))
            };
        }

        // 지도가 로드되면 데이터를 얹습니다.
        map.on('load', async () => {
            // 3. 3개 레벨 Parquet 로드 및 변환 (시도, 시군구, 읍면동)
            // 파일명은 'sido.parquet', 'sigungu.parquet', 'umd.parquet'으로 가정합니다.
            const sidoData = await loadAndConvertParquet('sido.parquet', 'sido');
            const sigunguData = await loadAndConvertParquet('sigungu.parquet', 'sigungu');
            const umdData = await loadAndConvertParquet('umd.parquet', 'umd');

            // 4. MapLibre에 소스 추가 (레벨별로 개별 소스 생성)
            map.addSource('sido-source', { type: 'geojson', data: sidoData });
            map.addSource('sigungu-source', { type: 'geojson', data: sigunguData });
            map.addSource('umd-source', { type: 'geojson', data: umdData });

            // 5. 레이어 추가 및 선 굵기/색상 스타일링 (중요)
            // 데이터가 겹치므로 '면(Fill)' 레이어는 투명하게, '선(Line)' 레이어만 굵기 다르게 추가합니다.
            
            // (1) 읍면동: 가장 가늘게 (가장 아래 레이어)
            map.addLayer({
                id: 'umd-layer',
                type: 'line',
                source: 'umd-source',
                paint: {
                    'line-color': '#999',  // 연한 회색
                    'line-width': 0.5       // 가늘게
                }
            });

            // (2) 시군구: 중간 굵기
            map.addLayer({
                id: 'sigungu-layer',
                type: 'line',
                source: 'sigungu-source',
                paint: {
                    'line-color': '#666',  // 중간 회색
                    'line-width': 1.5       // 중간
                }
            });

            // (3) 시도: 가장 굵게 (가장 위 레이어)
            map.addLayer({
                id: 'sido-layer',
                type: 'line',
                source: 'sido-source',
                paint: {
                    'line-color': '#333',  // 진한 회색
                    'line-width': 3         // 굵게
                }
            });

            // 6. [나중에] API 좌표 마커 추가 (예시)
            // 나중에 실제 API 데이터가 오면 이 부분을 실행하면 됩니다.
            const sampleApiPoints = [
                { lat: 37.5665, lng: 126.9780, name: '서울시청' },
                { lat: 35.1796, lng: 129.0756, name: '부산시청' }
            ];

            // API 좌표를 GeoJSON 소스로 추가
            map.addSource('api-points', {
                type: 'geojson',
                data: {
                    type: 'FeatureCollection',
                    features: sampleApiPoints.map(point => ({
                        type: 'Feature',
                        geometry: { type: 'Point', coordinates: [point.lng, point.lat] },
                        properties: { name: point.name }
                    }))
                }
            });

            // API 좌표 레이어 추가 (아이콘 표시)
            map.addLayer({
                id: 'api-points-layer',
                type: 'symbol', // 아이콘/텍스트 레이어
                source: 'api-points',
                layout: {
                    'icon-image': 'rocket-15', // 기본 스타일 내장 아이콘 이름 (또는 커스텀 이미지 등록 가능)
                    'icon-size': 1.5,
                    'text-field': '{name}', // 데이터의 name 속성 표시
                    'text-font': ['Open Sans Regular'], // 폰트 설정
                    'text-offset': [0, 0.6],
                    'text-anchor': 'top'
                }
            });
        });
    }

    initMap();
</script>
</body>
</html>
```

### 이 해결책의 작동 원리와 특징

1.  **Parquet 직접 처리**: `DuckDB-Wasm`이 브라우저 내부에서 작동하여 SQL 쿼리로 Parquet 파일을 읽고, `ST_AsGeoJSON` 함수를 이용해 공간 정보(`geom` 컬럼)를 브라우저가 다루기 좋은 GeoJSON 형태의 메모리 객체로 즉석에서 변환해 줍니다.
2.  **선 굵기 차등 적용**: **MapLibre GL JS**의 레이어 시스템을 활용합니다. 읍면동(최하층), 시군구(중간층), 시도(최상층) 순으로 `map.addLayer()`를 호출하여 나중에 추가된 레이어가 위에 그려지도록 합니다. 또한, 각 레이어의 `paint` 옵션 내 `line-width`를 통해 선 굵기를 미세하게 조절합니다. GPU 가속 덕분에 수만 개의 다각형 선도 매우 부드럽게 렌더링됩니다.
3.  **API 좌표 추가**: 나중에 API 데이터를 불러오면, 위 코드의 "6번" 섹션처럼 데이터를 GeoJSON 형태로 가공하여 **`map.addSource('api-points', { ... })`**로 추가하고, **`map.addLayer({ type: 'symbol', ... })`**를 통해 아이콘과 텍스트를 함께 지도 위에 표시할 수 있습니다.

**주의사항**: 이 솔루션은 브라우저 메모리에 의존하므로 읍면동 Parquet 파일이 너무 크면(수십 MB 이상) 로딩 속도가 느려지거나 브라우저가 버벅거릴 수 있습니다. 이럴 때는 PMTiles 같은 동적 타일링 방식이 필수적이지만, Parquet 직접 처리를 원하시므로 이 방식이 최선입니다.



혹시 사용하시는 Parquet 파일의 공간 정보 컬럼 이름이 'geom'이 아니거나, API 좌표 데이터의 형식(예: CSV 등)이 다르다면 말씀해 주세요. 그에 맞춰 SQL 쿼리나 데이터 가공 코드를 수정해 드리겠습니다.