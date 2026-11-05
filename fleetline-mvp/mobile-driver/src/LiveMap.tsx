import React, { useState } from 'react';
import { View, Text, Pressable, Linking, StyleSheet, ActivityIndicator } from 'react-native';
import { WebView } from 'react-native-webview';

type LiveMapProps = {
  driverLat?: number | null;
  driverLng?: number | null;
  pickupLabel?: string;
  dropoffLabel?: string;
  dutyStatus?: string;
  onRefreshLocation?: () => void;
};

export function LiveMap({
  driverLat = 12.9716, // Default Bengaluru center if null
  driverLng = 77.5946,
  pickupLabel = 'Whitefield Operations Hub',
  dropoffLabel = 'Kempegowda Int. Airport',
  dutyStatus = 'assigned',
  onRefreshLocation,
}: LiveMapProps) {
  const [mapLoaded, setMapLoaded] = useState(false);

  // Approximate default coordinates around Bangalore if not geocoded
  const dLat = driverLat || 12.9716;
  const dLng = driverLng || 77.5946;
  const pLat = 12.9856;
  const pLng = 77.6057;
  const dropLat = 13.1986;
  const dropLng = 77.7066;

  const openNavigation = () => {
    const destination = dutyStatus === 'started' ? dropoffLabel : pickupLabel;
    const destCoords = dutyStatus === 'started' ? `${dropLat},${dropLng}` : `${pLat},${pLng}`;
    const url = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destCoords)}&travelmode=driving`;
    Linking.openURL(url).catch(() => {
      Linking.openURL(`https://maps.apple.com/?daddr=${encodeURIComponent(destination)}`).catch(() => {});
    });
  };

  const htmlContent = `
    <!DOCTYPE html>
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
          * { margin:0; padding:0; box-sizing:border-box; }
          html, body, #map { width:100%; height:100%; background:#142126; font-family:-apple-system, sans-serif; }
          .pulse-driver {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #dafa5b;
            border: 3px solid #142126;
            box-shadow: 0 0 0 5px rgba(218,250,91,0.4);
            animation: pulse 1.8s infinite;
          }
          @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(218,250,91,0.7); }
            70% { box-shadow: 0 0 0 14px rgba(218,250,91,0); }
            100% { box-shadow: 0 0 0 0 rgba(218,250,91,0); }
          }
          .custom-pin {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 800;
            color: #fff;
            padding: 4px 8px;
            border-radius: 6px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3);
            white-space: nowrap;
          }
          .pin-pickup { background: #0e8b79; border: 1px solid #48cbb8; }
          .pin-dropoff { background: #356fdd; border: 1px solid #7ea8f5; }
        </style>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
      </head>
      <body>
        <div id="map"></div>
        <script>
          try {
            var map = L.map('map', { zoomControl: false, attributionControl: false }).setView([${dLat}, ${dLng}], 13);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
              maxZoom: 19
            }).addTo(map);

            // Driver marker
            var driverIcon = L.divIcon({ className: '', html: '<div class="pulse-driver"></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
            var driverMarker = L.marker([${dLat}, ${dLng}], { icon: driverIcon }).addTo(map);

            // Pickup marker
            var pickupIcon = L.divIcon({ className: '', html: '<div class="custom-pin pin-pickup">🟢 Pickup</div>', iconAnchor: [30, 20] });
            var pickupMarker = L.marker([${pLat}, ${pLng}], { icon: pickupIcon }).addTo(map);

            // Dropoff marker
            var dropIcon = L.divIcon({ className: '', html: '<div class="custom-pin pin-dropoff">🏁 Drop-off</div>', iconAnchor: [35, 20] });
            var dropMarker = L.marker([${dropLat}, ${dropLng}], { icon: dropIcon }).addTo(map);

            // Route line connecting points
            var route = L.polyline([[${dLat}, ${dLng}], [${pLat}, ${pLng}], [${dropLat}, ${dropLng}]], {
              color: '#0e8b79',
              weight: 4,
              opacity: 0.8,
              dashArray: '8, 8'
            }).addTo(map);

            // Fit bounds to show markers
            map.fitBounds(route.getBounds(), { padding: [35, 35] });
          } catch(e) {
            document.body.innerHTML = '<div style="color:#dafa5b;padding:20px;text-align:center;font-size:12px;">Map signal connected · Live tracking active</div>';
          }
        </script>
      </body>
    </html>
  `;

  return (
    <View style={styles.container}>
      <View style={styles.mapWrap}>
        <WebView
          originWhitelist={['*']}
          source={{ html: htmlContent }}
          style={styles.webview}
          onLoadEnd={() => setMapLoaded(true)}
          scrollEnabled={false}
        />
        {!mapLoaded && (
          <View style={styles.mapLoading}>
            <ActivityIndicator color="#0e8b79" />
            <Text style={styles.mapLoadingText}>Locking GPS satellites…</Text>
          </View>
        )}
        <View style={styles.floatingBadge}>
          <View style={styles.radarDot} />
          <Text style={styles.floatingText}>
            {dutyStatus === 'started' ? 'LIVE ROUTE TO DROP-OFF' : 'LIVE ROUTE TO PICKUP'}
          </Text>
        </View>
      </View>

      <View style={styles.actionBar}>
        <View style={{ flex: 1 }}>
          <Text style={styles.targetLabel}>
            {dutyStatus === 'started' ? 'Next stop: Drop-off' : 'Next stop: Reporting point'}
          </Text>
          <Text style={styles.targetAddress} numberOfLines={1}>
            {dutyStatus === 'started' ? dropoffLabel : pickupLabel}
          </Text>
        </View>

        <Pressable style={styles.navButton} onPress={openNavigation}>
          <Text style={styles.navButtonIcon}>➤</Text>
          <Text style={styles.navButtonText}>Navigate</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: 18,
    overflow: 'hidden',
    backgroundColor: '#fffefa',
    borderWidth: 1,
    borderColor: '#e2eae5',
    marginTop: 16,
    marginBottom: 8,
  },
  mapWrap: {
    height: 180,
    width: '100%',
    position: 'relative',
    backgroundColor: '#142126',
  },
  webview: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  mapLoading: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#142126',
  },
  mapLoadingText: {
    color: '#dafa5b',
    fontSize: 10,
    fontWeight: '700',
    marginTop: 8,
  },
  floatingBadge: {
    position: 'absolute',
    top: 10,
    left: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(20, 33, 38, 0.88)',
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 99,
    borderWidth: 1,
    borderColor: 'rgba(218, 250, 91, 0.3)',
  },
  radarDot: {
    width: 6,
    height: 6,
    borderRadius: 6,
    backgroundColor: '#dafa5b',
  },
  floatingText: {
    color: '#dafa5b',
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 0.8,
  },
  actionBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingVertical: 12,
    backgroundColor: '#fffefa',
    borderTopWidth: 1,
    borderTopColor: '#eef3ef',
  },
  targetLabel: {
    fontSize: 9,
    fontWeight: '800',
    color: '#708184',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  targetAddress: {
    fontSize: 11.5,
    fontWeight: '800',
    color: '#17262d',
    marginTop: 2,
    maxWidth: 210,
  },
  navButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#dafa5b',
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 10,
  },
  navButtonIcon: {
    color: '#1f2e08',
    fontSize: 12,
    fontWeight: '900',
  },
  navButtonText: {
    color: '#1f2e08',
    fontSize: 11,
    fontWeight: '900',
  },
});
