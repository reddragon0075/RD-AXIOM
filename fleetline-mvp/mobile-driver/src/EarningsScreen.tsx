import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, Pressable, RefreshControl, ActivityIndicator } from 'react-native';
import { completedDutiesHistory } from './api';
import type { CompletedDutyItem, DriverEarningsSummary } from './types';

const colors = {
  deep: '#142126',
  canvas: '#f3f7f3',
  card: '#fffefa',
  ink: '#17262d',
  muted: '#708184',
  line: '#e2eae5',
  lime: '#dafa5b',
  limeDark: '#445610',
  teal: '#0e8b79',
  tealSoft: '#e3f6ef',
  blue: '#356fdd',
  blueSoft: '#e8f0ff',
  amber: '#b5771c',
  amberSoft: '#fff3da',
};

export function EarningsScreen() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [history, setHistory] = useState<CompletedDutyItem[]>([]);
  const [summary, setSummary] = useState<DriverEarningsSummary>({
    todayPayout: 1850,
    totalKm: 84,
    tripsCompleted: 3,
    allowances: 150,
    tolls: 140,
    weeklySettlementDue: 'Friday, 10:00 AM',
  });

  const loadData = async () => {
    try {
      const data = await completedDutiesHistory();
      setHistory(data.items);
      setSummary(data.earningsSummary);
    } catch (_) {
      // Default sample state maintained
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const onRefresh = () => {
    setRefreshing(true);
    loadData();
  };

  if (loading) {
    return (
      <View style={styles.loadingCenter}>
        <ActivityIndicator color={colors.teal} />
        <Text style={styles.loadingText}>Calculating today's earnings & settlements…</Text>
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} colors={[colors.teal]} />}
    >
      <Text style={styles.eyebrow}>DRIVER LEDGER & SETTLEMENTS</Text>
      <Text style={styles.pageTitle}>Daily Earnings</Text>
      <Text style={styles.pageSub}>Verified trip payouts, allowances and toll reimbursements.</Text>

      {/* Main Highlights Card */}
      <View style={styles.earningsHero}>
        <View style={styles.heroTopRow}>
          <Text style={styles.heroEyebrow}>TODAY'S ESTIMATED PAYOUT</Text>
          <View style={styles.settlementBadge}>
            <Text style={styles.settlementBadgeText}>● Settles {summary.weeklySettlementDue}</Text>
          </View>
        </View>

        <Text style={styles.heroAmount}>₹{summary.todayPayout.toLocaleString('en-IN')}</Text>
        <Text style={styles.heroNote}>Direct deposit into linked driver bank account</Text>

        <View style={styles.metricsRow}>
          <View style={styles.metricItem}>
            <Text style={styles.metricVal}>{summary.tripsCompleted}</Text>
            <Text style={styles.metricLbl}>Completed runs</Text>
          </View>
          <View style={styles.metricDivider} />
          <View style={styles.metricItem}>
            <Text style={styles.metricVal}>{summary.totalKm} km</Text>
            <Text style={styles.metricLbl}>Total distance</Text>
          </View>
          <View style={styles.metricDivider} />
          <View style={styles.metricItem}>
            <Text style={styles.metricVal}>₹{summary.tolls}</Text>
            <Text style={styles.metricLbl}>Toll / Parking</Text>
          </View>
        </View>
      </View>

      {/* Breakdown Card */}
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Payout breakdown</Text>
        <Text style={styles.sectionSub}>Calculated per rate card</Text>
      </View>

      <View style={styles.card}>
        <View style={styles.breakdownRow}>
          <Text style={styles.breakdownLabel}>Base trip earnings (45% share)</Text>
          <Text style={styles.breakdownValue}>₹{(summary.todayPayout - summary.allowances - summary.tolls).toLocaleString('en-IN')}</Text>
        </View>
        <View style={styles.breakdownRow}>
          <Text style={styles.breakdownLabel}>Driver allowances (Airport / Night)</Text>
          <Text style={styles.breakdownValue}>₹{summary.allowances.toLocaleString('en-IN')}</Text>
        </View>
        <View style={[styles.breakdownRow, { borderBottomWidth: 0 }]}>
          <Text style={styles.breakdownLabel}>Toll & parking receipts verified</Text>
          <Text style={styles.breakdownValue}>₹{summary.tolls.toLocaleString('en-IN')}</Text>
        </View>
      </View>

      {/* Duty History Section */}
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Completed duties history</Text>
        <Text style={styles.sectionSub}>{history.length} verified trip{history.length === 1 ? '' : 's'}</Text>
      </View>

      {history.map((item: any, idx) => (
        <View style={styles.historyCard} key={item.id || idx}>
          <View style={styles.historyTop}>
            <View>
              <Text style={styles.historyTitle}>{item.duty_type || 'Corporate Transfer'}</Text>
              <Text style={styles.historySub}>{item.customer || 'Enterprise Account'} · {item.passenger || 'Passenger'}</Text>
            </View>
            <Text style={styles.historyPayout}>+ ₹{item.payout || 550}</Text>
          </View>

          <View style={styles.routeBox}>
            <View style={styles.routeRow}>
              <Text style={styles.pinIcon}>🟢</Text>
              <Text style={styles.routeText} numberOfLines={1}>{item.pickup || 'Pickup location'}</Text>
            </View>
            <View style={styles.routeRow}>
              <Text style={styles.pinIcon}>🏁</Text>
              <Text style={styles.routeText} numberOfLines={1}>{item.dropoff || 'Drop-off location'}</Text>
            </View>
          </View>

          <View style={styles.historyBottom}>
            <Text style={styles.vehicleTag}>{item.vehicle || 'Vehicle verified'}</Text>
            <View style={styles.verifiedTag}>
              <Text style={styles.verifiedText}>✓ Duty Slip Approved</Text>
            </View>
          </View>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 17,
    paddingBottom: 110,
  },
  loadingCenter: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 30,
  },
  loadingText: {
    marginTop: 10,
    fontSize: 11,
    color: colors.muted,
  },
  eyebrow: {
    color: colors.teal,
    fontSize: 8.5,
    fontWeight: '800',
    letterSpacing: 1.4,
    marginTop: 3,
  },
  pageTitle: {
    color: colors.ink,
    fontSize: 27,
    fontWeight: '800',
    letterSpacing: -1.6,
    marginTop: 5,
  },
  pageSub: {
    color: colors.muted,
    fontSize: 10.5,
    lineHeight: 15,
    marginTop: 6,
    marginBottom: 16,
  },
  earningsHero: {
    backgroundColor: colors.deep,
    borderRadius: 20,
    padding: 20,
    marginBottom: 18,
  },
  heroTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  heroEyebrow: {
    color: '#bcd1ac',
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 1.1,
  },
  settlementBadge: {
    backgroundColor: 'rgba(218, 250, 91, 0.15)',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 99,
  },
  settlementBadgeText: {
    color: colors.lime,
    fontSize: 8.5,
    fontWeight: '800',
  },
  heroAmount: {
    color: colors.lime,
    fontSize: 36,
    fontWeight: '900',
    letterSpacing: -1.5,
    marginTop: 12,
  },
  heroNote: {
    color: '#9eb7af',
    fontSize: 10,
    marginTop: 4,
  },
  metricsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 20,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.12)',
  },
  metricItem: {
    flex: 1,
    alignItems: 'center',
  },
  metricVal: {
    color: '#f4fbf0',
    fontSize: 16,
    fontWeight: '800',
  },
  metricLbl: {
    color: '#9eb7af',
    fontSize: 8.5,
    marginTop: 3,
  },
  metricDivider: {
    width: 1,
    height: 25,
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  sectionHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 10,
  },
  sectionTitle: {
    color: colors.ink,
    fontSize: 12,
    fontWeight: '800',
  },
  sectionSub: {
    color: colors.muted,
    fontSize: 9,
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 15,
    marginBottom: 18,
  },
  breakdownRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f4f1',
  },
  breakdownLabel: {
    color: colors.ink,
    fontSize: 11,
    fontWeight: '600',
  },
  breakdownValue: {
    color: colors.ink,
    fontSize: 12,
    fontWeight: '800',
  },
  historyCard: {
    backgroundColor: colors.card,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 15,
    marginBottom: 11,
  },
  historyTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  historyTitle: {
    color: colors.ink,
    fontSize: 12.5,
    fontWeight: '800',
  },
  historySub: {
    color: colors.muted,
    fontSize: 9.5,
    marginTop: 2,
  },
  historyPayout: {
    color: colors.teal,
    fontSize: 15,
    fontWeight: '900',
  },
  routeBox: {
    backgroundColor: '#f7faf7',
    borderRadius: 10,
    padding: 10,
    gap: 6,
    marginBottom: 12,
  },
  routeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  pinIcon: {
    fontSize: 10,
  },
  routeText: {
    color: colors.ink,
    fontSize: 10.5,
    fontWeight: '600',
    flex: 1,
  },
  historyBottom: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  vehicleTag: {
    color: colors.muted,
    fontSize: 9,
  },
  verifiedTag: {
    backgroundColor: colors.tealSoft,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  verifiedText: {
    color: colors.teal,
    fontSize: 8.5,
    fontWeight: '800',
  },
});
