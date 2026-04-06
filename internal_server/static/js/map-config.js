/**
 * Map Tile Provider Configuration
 * Change PROVIDER to switch between different tile sources
 *
 * Options:
 *   'osm'       - OpenStreetMap (may not work in China)
 *   'cartodb'   - CartoDB Positron (light, clean)
 *   'esri'      - Esri World Street Map
 *   'esri_sat'  - Esri World Imagery (satellite)
 *   'geoq'      - GeoQ China (智图, works in China)
 *   'gaode'     - Gaode/Amap (高德, works in China but may need API key)
 */

const MAP_CONFIG = {
    // Current provider - change this to switch
    PROVIDER: 'geoq',

    // Tile providers configuration
    PROVIDERS: {
        osm: {
            url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            options: {
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 19,
                subdomains: ['a', 'b', 'c']
            }
        },
        cartodb: {
            url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
            options: {
                attribution: '&copy; CartoDB',
                maxZoom: 19,
                subdomains: 'abcd'
            }
        },
        esri: {
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
            options: {
                attribution: '&copy; Esri',
                maxZoom: 19
            }
        },
        esri_sat: {
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            options: {
                attribution: '&copy; Esri',
                maxZoom: 19
            }
        },
        geoq: {
            // GeoQ - Works in China without API key
            url: 'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}',
            options: {
                attribution: '&copy; GeoQ 智图',
                maxZoom: 18
            }
        },
        geoq_sat: {
            // GeoQ Satellite
            url: 'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineStreetPurplishBlue/MapServer/tile/{z}/{y}/{x}',
            options: {
                attribution: '&copy; GeoQ 智图',
                maxZoom: 18
            }
        },
        gaode: {
            // Gaode/Amap - Works in China
            url: 'http://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
            options: {
                attribution: '&copy; 高德地图',
                maxZoom: 18,
                subdomains: ['1', '2', '3', '4']
            }
        }
    },

    // Get tile layer for current provider
    getTileLayer: function() {
        const provider = this.PROVIDERS[this.PROVIDER];
        return L.tileLayer(provider.url, provider.options);
    },

    // Get all available layers for layer control
    getAllLayers: function() {
        const layers = {};
        for (const [name, config] of Object.entries(this.PROVIDERS)) {
            layers[name.toUpperCase()] = L.tileLayer(config.url, config.options);
        }
        return layers;
    }
};

// Export for use in other scripts
if (typeof window !== 'undefined') {
    window.MAP_CONFIG = MAP_CONFIG;
}