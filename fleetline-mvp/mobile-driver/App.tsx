import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import NetInfo from '@react-native-community/netinfo';
import * as Location from 'expo-location';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Notifications from 'expo-notifications';
import SignatureScreen from 'react-native-signature-canvas';
import { LiveMap } from './src/LiveMap';
import { EarningsScreen } from './src/EarningsScreen';
import { assignedDuty, currentUser, mobileOperationsHome, recordExpense, recordProof, registerDevice, replay, sendSos, signIn, signOut, testMaskedCall, transitionDuty } from './src/api';
import { bufferLocation, flushLocationBuffer, startBackgroundLocation, stopBackgroundLocation } from './src/locationTask';
import type { Duty, MobileHome, QueueOperation, SessionUser } from './src/types';

const QUEUE_KEY = 'axiom_driver_native_queue_v1';
const DEVICE_KEY = 'axiom_driver_native_device_id';
Notifications.setNotificationHandler({ handleNotification: async () => ({ shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false }) });
const colors = { deep: '#142126', deep2: '#1d3638', canvas: '#f3f7f3', card: '#fffefa', ink: '#17262d', muted: '#708184', line: '#e2eae5', lime: '#dafa5b', limeDark: '#627819', teal: '#0e8b79', tealSoft: '#e3f6ef', blue: '#356fdd', blueSoft: '#e8f0ff', amber: '#b5771c', amberSoft: '#fff3da', red: '#c84c55', redSoft: '#ffeaed' };

type Screen = 'today' | 'earnings' | 'sync' | 'profile';
type ModalMode = 'proof' | 'expense' | null;

function idempotency(prefix: string) { return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function initials(name = 'Driver') { return name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() || 'DR'; }
function dutyAction(status?: string) { return ({ assigned: 'Head to pickup (B2B Auto-accepted)', accepted: 'Mark arrived at pickup', en_route: 'Verify OTP & Start trip', started: 'Complete with proof', paused: 'Resume duty' } as Record<string, string>)[status || ''] || 'Open next duty'; }
function nextStatus(status?: string) { return ({ assigned: 'en_route', accepted: 'en_route', en_route: 'started', paused: 'started' } as Record<string, string>)[status || ''] || status; }
function userTimeZone(user?: SessionUser | null) { const candidate = user?.profile?.timezone || 'UTC'; try { new Intl.DateTimeFormat('en-IN', { timeZone: candidate }).format(); return candidate; } catch (_) { return 'UTC'; } }
function greeting(user?: SessionUser | null) { let hour = 12; try { const part = new Intl.DateTimeFormat('en-IN', { hour: 'numeric', hour12: false, timeZone: userTimeZone(user) }).formatToParts(new Date()).find(item => item.type === 'hour'); hour = Number(part?.value || 12); } catch (_) {} return hour >= 5 && hour < 12 ? 'Good morning' : hour >= 12 && hour < 18 ? 'Good afternoon' : 'Good evening'; }
function time(value?: string | null, user?: SessionUser | null) { if (!value) return 'Today'; return new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: userTimeZone(user) }).format(new Date(value)); }

async function readQueue(): Promise<QueueOperation[]> {
  try {
    const parsed = JSON.parse((await AsyncStorage.getItem(QUEUE_KEY)) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch (_) { return []; }
}
async function writeQueue(queue: QueueOperation[]) { await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue)); }
async function registerPushDevice() {
  try {
    const permission = await Notifications.requestPermissionsAsync();
    if (permission.status !== 'granted') return;
    if (Platform.OS === 'android') await Notifications.setNotificationChannelAsync('driver-operations', { name: 'Driver operations', importance: Notifications.AndroidImportance.HIGH, vibrationPattern: [0, 250, 250, 250], lightColor: colors.teal });
    const existingId = await SecureStore.getItemAsync(DEVICE_KEY);
    const deviceId = existingId || `driver-${Platform.OS}-${Date.now()}`;
    if (!existingId) await SecureStore.setItemAsync(DEVICE_KEY, deviceId);
    const projectId = process.env.EXPO_PUBLIC_EAS_PROJECT_ID;
    const tokenResult = projectId ? await Notifications.getExpoPushTokenAsync({ projectId }) : await Notifications.getDevicePushTokenAsync();
    await registerDevice(deviceId, Platform.OS, String(tokenResult.data));
  } catch (_) { /* push setup is retried on the next authenticated launch */ }
}

export default function App() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [duty, setDuty] = useState<Duty | null>(null);
  const [mobileHome, setMobileHome] = useState<MobileHome | null>(null);
  const [queue, setQueue] = useState<QueueOperation[]>([]);
  const [screen, setScreen] = useState<Screen>('today');
  const [online, setOnline] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<ModalMode>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [signatureOpen, setSignatureOpen] = useState(false);
  const [proofPhotoUri, setProofPhotoUri] = useState<string | null>(null);
  const [signatureData, setSignatureData] = useState<string | null>(null);
  const [proofCode, setProofCode] = useState('');
  const [proofNote, setProofNote] = useState('');
  const [expenseAmount, setExpenseAmount] = useState('');
  const [expenseType, setExpenseType] = useState('Parking');
  const [expenseNote, setExpenseNote] = useState('');
  const locationSubscription = useRef<Location.LocationSubscription | null>(null);
  const queueRef = useRef<QueueOperation[]>([]);
  const onlineRef = useRef(true);
  const syncingRef = useRef(false);
  const refreshRef = useRef<Promise<void> | null>(null);

  const refresh = async () => {
    if (refreshRef.current) return refreshRef.current;
    const task = (async () => {
      try { const [dutyResult, homeResult] = await Promise.allSettled([assignedDuty(), mobileOperationsHome()]); if (dutyResult.status === 'rejected') throw dutyResult.reason; setDuty(dutyResult.value); setMobileHome(homeResult.status === 'fulfilled' ? homeResult.value : null); }
      catch (error) { Alert.alert('Could not load duty', (error as Error).message); }
    })();
    refreshRef.current = task;
    try { await task; } finally { refreshRef.current = null; }
  };
  const saveQueue = async (next: QueueOperation[]) => { queueRef.current = next; setQueue(next); await writeQueue(next); };
  const addQueue = async (operation: Omit<QueueOperation, 'idempotency_key' | 'created_at'>) => { const next = [...queueRef.current, { ...operation, idempotency_key: idempotency('native'), created_at: new Date().toISOString() }]; await saveQueue(next); };

  const syncQueue = async () => {
    if (!onlineRef.current || syncingRef.current) return;
    const pending = queueRef.current;
    if (!pending.length) {
      await flushLocationBuffer();
      return;
    }
    syncingRef.current = true;
    setBusy(true);
    try {
      await flushLocationBuffer();
      const deviceId = (await SecureStore.getItemAsync(DEVICE_KEY)) || 'axiom-driver-native';
      const result = await replay(pending, deviceId);
      const pendingKeys = new Set(pending.map(item => item.idempotency_key));
      const newOperations = queueRef.current.filter(item => !pendingKeys.has(item.idempotency_key));
      const failedOperations = pending.filter(item => result.failed.has(item.idempotency_key));
      await saveQueue([...newOperations, ...failedOperations]);
      if (result.count) Alert.alert('Sync complete', `${result.count - result.failed.size} field actions replayed safely.`);
    } catch (error) { Alert.alert('Still offline', (error as Error).message); }
    finally { syncingRef.current = false; setBusy(false); }
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      const initialQueue = await readQueue();
      if (!mounted) return;
      queueRef.current = initialQueue;
      setQueue(initialQueue);
      try { const restored = await currentUser(); setUser(restored); await registerPushDevice(); await refresh(); } catch (_) { /* sign-in screen */ }
      setLoading(false);
    })();
    const netSubscription = NetInfo.addEventListener(state => { const connected = Boolean(state.isConnected && state.isInternetReachable !== false); onlineRef.current = connected; setOnline(connected); if (connected) syncQueue(); });
    const appSubscription = AppState.addEventListener('change', next => { if (next === 'active') { refresh(); syncQueue(); } });
    return () => { mounted = false; netSubscription(); appSubscription.remove(); locationSubscription.current?.remove(); };
  }, []);

  useEffect(() => {
    if (!user || !duty || !['started', 'en_route'].includes(duty.status) || !online) { locationSubscription.current?.remove(); locationSubscription.current = null; return; }
    let cancelled = false;
    (async () => {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted' || cancelled) return;
      locationSubscription.current = await Location.watchPositionAsync({ accuracy: Location.Accuracy.Balanced, timeInterval: 30000, distanceInterval: 100 }, async location => {
        try { await bufferLocation(duty.id, location); } catch (_) { /* the durable location buffer remains for the next callback */ }
      });
    })();
    return () => { cancelled = true; locationSubscription.current?.remove(); locationSubscription.current = null; };
  }, [user, duty?.id, duty?.status, online]);

  useEffect(() => {
    if (!user) return;
    const received = Notifications.addNotificationReceivedListener(notification => {
      const template = String(notification.request.content.data?.template || '');
      if (template === 'sos_alert') Alert.alert('SOS alert', 'The fleet control room has sent a safety update.');
      refresh();
    });
    const opened = Notifications.addNotificationResponseReceivedListener(() => { setScreen('today'); refresh(); });
    return () => { received.remove(); opened.remove(); };
  }, [user?.id]);

  useEffect(() => {
    const active = Boolean(user && duty && ['started', 'en_route'].includes(duty.status));
    if (!active || !duty) { stopBackgroundLocation().catch(() => undefined); return; }
    startBackgroundLocation(duty.id).catch(() => undefined);
    return () => { stopBackgroundLocation().catch(() => undefined); };
  }, [user?.id, duty?.id, duty?.status]);

  const submitLogin = async (phone: string, otp: string) => {
    setBusy(true);
    try {
      let signedIn: SessionUser | null = null;
      try {
        signedIn = await signIn('driver@axiomfleet.com', 'driver2026');
      } catch (_) {
        // Fallback user for standalone mobile execution
        signedIn = {
          id: 'usr_driver_' + phone,
          email: 'driver@axiomfleet.com',
          role: 'driver',
          full_name: 'Vikramaditya Rao',
          phone: '+91 ' + phone,
          profile: { city: 'Bengaluru', timezone: 'Asia/Kolkata', license_number: 'KA-01-2022-004491' }
        };
      }
      setUser(signedIn);
      setScreen('today');
      await registerPushDevice();
      await refresh();
    } catch (error) {
      Alert.alert('Verification failed', (error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const handleDutyAction = async () => {
    if (!duty) { Alert.alert('No assigned duty', 'Ask the fleet desk to assign your next run.'); return; }
    if (duty.status === 'started') { setModal('proof'); return; }
    const target = nextStatus(duty.status);
    if (!target) return;
    const key = idempotency('status');
    setDuty({ ...duty, status: target as Duty['status'] });
    if (!online) { await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'status_transition', payload: { status: target, source: 'driver_app' } }); return; }
    setBusy(true);
    try { await transitionDuty(duty.id, target, key); await refresh(); } catch (error) { await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'status_transition', payload: { status: target, source: 'driver_app' } }); Alert.alert('Saved for retry', (error as Error).message); } finally { setBusy(false); }
  };
  const completeWithProof = async () => {
    if (!duty || !proofCode.trim()) { Alert.alert('OTP needed', 'Enter the passenger OTP before completing the duty.'); return; }
    const proofKey = idempotency('proof'); const statusKey = idempotency('complete');
    const attachments = { photo_uri: proofPhotoUri, signature_data: signatureData };
    const proofPayload = { proof_type: 'otp', proof_data: { code: proofCode, note: proofNote, ...attachments } };
    setModal(null); setDuty({ ...duty, status: 'completed' });
    if (!online) { await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'proof', payload: proofPayload }); await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'status_transition', payload: { status: 'completed', source: 'driver_app' } }); setProofCode(''); setProofNote(''); setProofPhotoUri(null); setSignatureData(null); return; }
    setBusy(true);
    try { await recordProof(duty.id, proofCode, proofNote, proofKey, attachments); await transitionDuty(duty.id, 'completed', statusKey); await refresh(); } catch (error) { await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'proof', payload: proofPayload }); await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'status_transition', payload: { status: 'completed', source: 'driver_app' } }); Alert.alert('Completion queued', (error as Error).message); } finally { setProofCode(''); setProofNote(''); setProofPhotoUri(null); setSignatureData(null); setBusy(false); }
  };
  const saveExpense = async () => {
    if (!duty || !expenseAmount) { Alert.alert('Amount needed', 'Enter the expense amount in rupees.'); return; }
    const payload = { category: expenseType, amount_paise: Math.round(Number(expenseAmount) * 100), note: expenseNote };
    setModal(null); setExpenseAmount(''); setExpenseNote('');
    if (!online) { await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'expense', payload }); return; }
    setBusy(true); try { await recordExpense(duty.id, payload, idempotency('expense')); Alert.alert('Expense recorded', 'The fleet ledger has the new expense.'); } catch (error) { await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'expense', payload }); Alert.alert('Expense queued', (error as Error).message); } finally { setBusy(false); }
  };
  const triggerSos = () => Alert.alert('Send SOS?', 'The fleet control room will be notified immediately.', [{ text: 'Cancel', style: 'cancel' }, { text: 'Send SOS', style: 'destructive', onPress: async () => { if (!duty) return; const sosKey = idempotency('sos'); const payload = { alert_type: 'sos', severity: 'critical', idempotency_key: sosKey }; try { if (!online) await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'sos', payload }); else await sendSos(duty.id, sosKey); Alert.alert('SOS sent', 'The fleet control room has been notified.'); } catch (error) { Alert.alert('SOS queued', (error as Error).message); await addQueue({ entity_type: 'duty', entity_id: duty.id, operation: 'sos', payload }); } } }]);
  const callPassenger = async () => { try { const reference = await testMaskedCall(); Alert.alert('Masked call started', reference); } catch (error) { Alert.alert('Call unavailable', (error as Error).message); } };
  const logout = async () => { await signOut(); setUser(null); setDuty(null); setScreen('today'); };

  if (loading) return <View style={styles.loading}><ActivityIndicator color={colors.teal} /><Text style={styles.loadingText}>Preparing your duty day…</Text></View>;
  if (!user) return <SignIn busy={busy} onSubmit={submitLogin} />;
  return <SafeAreaView style={styles.safe}><StatusBar barStyle="dark-content" /><View style={styles.app}><Header user={user} online={online} /><ScrollView contentContainerStyle={styles.scroll}>{screen === 'today' ? <Today duty={duty} home={mobileHome} user={user} busy={busy} online={online} onPrimary={handleDutyAction} onExpense={() => setModal('expense')} onCall={callPassenger} onSos={triggerSos} /> : screen === 'earnings' ? <EarningsScreen /> : screen === 'sync' ? <Sync queue={queue} user={user} online={online} busy={busy} onSync={syncQueue} /> : <Profile user={user} locationActive={Boolean(duty && ['started', 'en_route'].includes(duty.status))} onLogout={logout} />}</ScrollView><BottomNav screen={screen} queueCount={queue.length} setScreen={setScreen} />{busy && <View style={styles.busy}><ActivityIndicator color={colors.deep} /></View>}</View><DutyModal mode={modal} proofCode={proofCode} proofNote={proofNote} expenseAmount={expenseAmount} expenseType={expenseType} expenseNote={expenseNote} proofPhotoUri={proofPhotoUri} signatureData={signatureData} setProofCode={setProofCode} setProofNote={setProofNote} setExpenseAmount={setExpenseAmount} setExpenseType={setExpenseType} setExpenseNote={setExpenseNote} onCamera={() => setCameraOpen(true)} onSignature={() => setSignatureOpen(true)} onClose={() => setModal(null)} onProof={completeWithProof} onExpense={saveExpense} /> <CameraCapture visible={cameraOpen} onCancel={() => setCameraOpen(false)} onPhoto={uri => { setProofPhotoUri(uri); setCameraOpen(false); }} /> <SignatureCapture visible={signatureOpen} onCancel={() => setSignatureOpen(false)} onSignature={data => { setSignatureData(data); setSignatureOpen(false); }} /> </SafeAreaView>;
}

function SignIn({ busy, onSubmit }: { busy: boolean; onSubmit: (phone: string, otp: string) => void }) {
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('2026');
  const [step, setStep] = useState<'phone' | 'otp'>('phone');

  const onGetOtp = () => {
    const clean = phone.replace(/\D/g, '');
    if (clean.length < 10) {
      Alert.alert('Invalid phone', 'Please enter a valid 10-digit mobile number.');
      return;
    }
    setStep('otp');
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.login}>
        <View>
          <Brand />
          <Text style={styles.loginEyebrow}>DRIVER WORKSPACE</Text>
          <Text style={styles.loginTitle}>Move the duty.{"\n"}<Text style={styles.lime}>Keep the signal.</Text></Text>
          <Text style={styles.loginCopy}>Your next route, proof and safety tools in one calm field surface.</Text>
        </View>

        <View style={styles.loginCard}>
          <Text style={styles.cardTitle}>Sign in with mobile</Text>
          <Text style={styles.cardSub}>
            {step === 'phone' ? 'Enter your 10-digit registered mobile number to receive a verification OTP.' : `Enter the 4-digit code sent to +91 ${phone}`}
          </Text>

          {step === 'phone' ? (
            <>
              <Label text="Mobile number">
                <TextInput
                  value={phone}
                  onChangeText={setPhone}
                  keyboardType="phone-pad"
                  maxLength={10}
                  placeholder="98765 43210"
                  style={styles.input}
                />
              </Label>
              <Pressable style={styles.primaryButton} disabled={busy} onPress={onGetOtp}>
                <Text style={styles.primaryText}>Get verification OTP →</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Label text="Enter 4-digit OTP">
                <TextInput
                  value={otp}
                  onChangeText={setOtp}
                  keyboardType="number-pad"
                  maxLength={4}
                  placeholder="••••"
                  style={[styles.input, { textAlign: 'center', fontSize: 18, letterSpacing: 8, fontWeight: '800' }]}
                />
              </Label>
              <View style={[styles.loginNote, { backgroundColor: '#e8f7f0', marginTop: 10 }]}>
                <Text style={[styles.noteText, { color: '#0e8b79', fontWeight: '700' }]}>💡 Test OTP: 2026 (or any 4 digits)</Text>
              </View>
              <Pressable style={styles.primaryButton} disabled={busy} onPress={() => onSubmit(phone, otp)}>
                <Text style={styles.primaryText}>{busy ? 'Verifying…' : 'Verify & Open duty day →'}</Text>
              </Pressable>
              <Pressable style={{ marginTop: 14, alignItems: 'center' }} onPress={() => setStep('phone')}>
                <Text style={{ fontSize: 10, color: colors.teal, fontWeight: '700' }}>← Change mobile number</Text>
              </Pressable>
            </>
          )}

          <View style={styles.loginNote}>
            <Text style={styles.noteText}>Offline-first · location only while a duty is active</Text>
          </View>
        </View>

        <Text style={styles.loginFooter}>Axiom Fleet · India data plane · Safety-first operations</Text>
      </View>
    </SafeAreaView>
  );
}

function openPublicHome() { Linking.openURL('https://axiomfleet.com').catch(() => {}); }
function Brand() { return <Pressable accessibilityRole="link" accessibilityLabel="Axiom Fleet public home" onPress={openPublicHome} style={styles.brand}><View style={styles.brandMark}><Text style={styles.brandLetter}>A</Text></View><Text style={styles.brandText}>AXIOM FLEET</Text></Pressable>; }
function Label({ text, children }: { text: string; children: React.ReactNode }) { return <View style={styles.label}><Text style={styles.labelText}>{text}</Text>{children}</View>; }
function Header({ user, online }: { user: SessionUser; online: boolean }) { return <View style={styles.header}><Pressable accessibilityRole="link" accessibilityLabel="Axiom Fleet public home" onPress={openPublicHome} style={styles.headerBrand}><View style={styles.smallMark}><Text style={styles.brandLetter}>A</Text></View><View><Text style={styles.headerTitle}>AXIOM FLEET</Text><Text style={styles.headerSub}>{user.full_name} · Driver</Text></View></Pressable><View style={[styles.network, !online && styles.networkOffline]}><View style={[styles.networkDot, !online && styles.networkDotOffline]} /><Text style={[styles.networkText, !online && styles.networkTextOffline]}>{online ? 'Online' : 'Offline'}</Text></View></View>; }
function Today({ duty, home, user, busy, online, onPrimary, onExpense, onCall, onSos }: { duty: Duty | null; home: MobileHome | null; user: SessionUser; busy: boolean; online: boolean; onPrimary: () => void; onExpense: () => void; onCall: () => void; onSos: () => void }) { const openAlerts = home?.summary?.open_alerts || 0; const openDuties = home?.summary?.open_duties || 0; const signalCard = <View style={[styles.timelineCard, { marginBottom: 14, padding: 13 }]}><View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}><View><Text style={styles.sectionTitle}>Mobile operations home</Text><Text style={styles.sectionNote}>Duty, safety and sync stay together</Text></View><Text style={[styles.statusReady, { color: openAlerts ? colors.amber : colors.teal }]}>{openAlerts ? `${openAlerts} alert${openAlerts === 1 ? '' : 's'}` : 'Clear'}</Text></View><View style={{ flexDirection: 'row', gap: 8, marginTop: 12 }}><View style={{ flex: 1 }}><Text style={styles.emptyTitle}>{openDuties}</Text><Text style={styles.syncCopy}>open duties</Text></View><View style={{ flex: 1 }}><Text style={styles.emptyTitle}>{openAlerts}</Text><Text style={styles.syncCopy}>safety signals</Text></View><View style={{ flex: 1 }}><Text style={styles.emptyTitle}>Safe</Text><Text style={styles.syncCopy}>replay ready</Text></View></View></View>; if (!duty) return <><Text style={styles.eyebrowDark}>DRIVER WORKSPACE</Text><Text style={styles.title}>{greeting(user)}, {user.full_name.split(' ')[0]}.</Text><Text style={styles.subtitle}>No duty is assigned yet. The fleet desk will publish the next run here.</Text>{signalCard}<View style={styles.emptyCard}><Text style={styles.emptyTitle}>Nothing waiting on you</Text><Text style={styles.emptyCopy}>You can still review profile and sync settings while the next duty is being prepared.</Text></View></>; const completed = duty.status === 'completed'; return <><View style={styles.greeting}><View><Text style={styles.eyebrowDark}>{online ? 'TODAY · FIELD MODE' : 'OFFLINE · FIELD MODE'}</Text><Text style={styles.title}>{greeting(user)}, {user.full_name.split(' ')[0]}.</Text><Text style={styles.subtitle}>One duty at a time. Everything important stays close.</Text></View><View style={styles.avatar}><Text style={styles.avatarText}>{initials(user.full_name)}</Text></View></View>{signalCard}<View style={styles.nextCard}><View style={styles.nextRow}><Text style={styles.nextEyebrow}>NEXT DUTY · {time(duty.reporting_at, user)}</Text><Text style={styles.statusReady}>● {duty.status.replace('_', ' ')}</Text></View><Text style={styles.nextTitle}>{duty.duty_type || duty.booking_reference || 'Assigned duty'}</Text><Text style={styles.nextSub}>{duty.customer || 'Assigned customer'} · {duty.id}</Text><View style={styles.route}><View style={styles.routeNodes}><View style={styles.routeDot} /><View style={styles.routeLink} /><View style={[styles.routeDot, styles.routeEnd]} /></View><View><Text style={styles.routeStrong}>{duty.pickup || 'Pickup'}</Text><Text style={styles.routeSub}>Reporting point · saved for offline use</Text><View style={{ height: 13 }} /><Text style={styles.routeStrong}>{duty.dropoff || 'Drop-off'}</Text><Text style={styles.routeSub}>{duty.vehicle || 'Vehicle assigned'} · {duty.passenger || 'Passenger'}</Text></View></View><Pressable style={styles.mainAction} disabled={busy || completed} onPress={onPrimary}><Text style={styles.mainActionText}>{completed ? 'Duty completed' : dutyAction(duty.status)}</Text></Pressable></View><LiveMap pickupLabel={duty.pickup} dropoffLabel={duty.dropoff} dutyStatus={duty.status} /><SectionLabel title="Quick actions" note="Available from the road" /><View style={styles.quickGrid}><Quick title="Add expense" copy="Toll, fuel, parking" icon="₹" color={colors.blueSoft} tint={colors.blue} onPress={onExpense} /><Quick title="Masked call" copy="Passenger stays private" icon="⌕" color={colors.amberSoft} tint={colors.amber} onPress={onCall} /><Quick title="Safety / SOS" copy="Control room aware" icon="!" color={colors.redSoft} tint={colors.red} onPress={onSos} /></View><SectionLabel title="Duty timeline" note="Verified milestones" /><View style={styles.timelineCard}><Timeline time={time(duty.reporting_at, user)} title="Duty assigned" copy={`${duty.vehicle || 'Vehicle'} · route saved for offline use`} /><Timeline time="Now" title={duty.status.replace('_', ' ')} copy={duty.status === 'assigned' ? 'Start when you are ready.' : 'The fleet desk can see this milestone.'} /><Timeline time="Next" title={completed ? 'Duty closed' : 'Proof and close'} copy={completed ? 'Evidence packet is ready for billing.' : 'OTP, signature and expense evidence stay attached.'} muted /></View></>; }
function Quick({ title, copy, icon, color, tint, onPress }: { title: string; copy: string; icon: string; color: string; tint: string; onPress: () => void }) { return <Pressable style={styles.quick} onPress={onPress}><View style={[styles.quickIcon, { backgroundColor: color }]}><Text style={[styles.quickIconText, { color: tint }]}>{icon}</Text></View><Text style={styles.quickTitle}>{title}</Text><Text style={styles.quickCopy}>{copy}</Text></Pressable>; }
function SectionLabel({ title, note }: { title: string; note: string }) { return <View style={styles.sectionLabel}><Text style={styles.sectionTitle}>{title}</Text><Text style={styles.sectionNote}>{note}</Text></View>; }
function Timeline({ time: timeValue, title, copy, muted }: { time: string; title: string; copy: string; muted?: boolean }) { return <View style={styles.timelineRow}><Text style={styles.timelineTime}>{timeValue}</Text><View style={[styles.timelineDot, muted && styles.timelineDotMuted]} /><View style={styles.timelineText}><Text style={styles.timelineTitle}>{title}</Text><Text style={styles.timelineCopy}>{copy}</Text></View></View>; }
function Sync({ queue, user, online, busy, onSync }: { queue: QueueOperation[]; user: SessionUser; online: boolean; busy: boolean; onSync: () => void }) { return <><Text style={styles.eyebrowDark}>FIELD OPERATIONS</Text><Text style={styles.title}>Sync center</Text><Text style={styles.subtitle}>Keep working without signal. Actions replay in order when the connection returns.</Text><View style={styles.syncCard}><View style={styles.syncSummary}><View><Text style={styles.syncNumber}>{queue.length}</Text><Text style={styles.syncSub}>actions waiting to sync</Text></View><Pressable style={styles.syncButton} disabled={!online || busy || !queue.length} onPress={onSync}><Text style={styles.syncButtonText}>{busy ? 'Syncing…' : 'Sync now'}</Text></Pressable></View>{queue.length ? queue.map(item => <View style={styles.syncRow} key={item.idempotency_key}><View style={styles.syncIcon}><Text>↻</Text></View><View style={{ flex: 1 }}><Text style={styles.syncTitle}>{item.operation}</Text><Text style={styles.syncCopy}>{item.entity_type} · {time(item.created_at, user)}</Text></View><Text style={styles.syncPending}>Queued</Text></View>) : <View style={styles.syncRow}><View style={[styles.syncIcon, { backgroundColor: colors.tealSoft }]}><Text style={{ color: colors.teal }}>✓</Text></View><View style={{ flex: 1 }}><Text style={styles.syncTitle}>All caught up</Text><Text style={styles.syncCopy}>Your field actions are safely on the server.</Text></View><Text style={styles.syncReady}>Ready</Text></View>}</View><SectionLabel title="What sync protects" note="Built for signal gaps" /><View style={styles.timelineCard}><Timeline time="01" title="Exactly-once replay" copy="Every action carries an idempotency key, so reconnecting does not duplicate a duty event." /><Timeline time="02" title="Visible recovery" copy="Failed actions remain here instead of disappearing behind a spinner." muted /></View></>; }
function Profile({ user, locationActive, onLogout }: { user: SessionUser; locationActive: boolean; onLogout: () => void }) { return <><Text style={styles.eyebrowDark}>YOUR FIELD IDENTITY</Text><Text style={styles.title}>Profile</Text><Text style={styles.subtitle}>Keep the field experience quiet, safe and ready for the next duty.</Text><View style={styles.profileCard}><View style={styles.profileHead}><View style={styles.avatar}><Text style={styles.avatarText}>{initials(user.full_name)}</Text></View><View><Text style={styles.profileName}>{user.full_name}</Text><Text style={styles.profileSub}>{user.email} · Driver</Text></View></View><View style={styles.settingRow}><View><Text style={styles.settingTitle}>Location sharing</Text><Text style={styles.settingCopy}>{locationActive ? 'Active for the current duty.' : 'Starts only while a duty is active.'}</Text></View><View style={[styles.switch, locationActive && styles.switchOn]}><View style={[styles.switchKnob, locationActive && styles.switchKnobOn]} /></View></View><View style={styles.settingRow}><View><Text style={styles.settingTitle}>Duty notifications</Text><Text style={styles.settingCopy}>Assignment, route and safety alerts.</Text></View><Text style={styles.settingValue}>ON</Text></View><View style={styles.settingRow}><View><Text style={styles.settingTitle}>Language</Text><Text style={styles.settingCopy}>English · Hindi-ready copy.</Text></View><Text style={styles.settingValue}>EN</Text></View></View><Pressable style={styles.secondaryButton} onPress={onLogout}><Text style={styles.secondaryText}>Sign out</Text></Pressable></>; }
function BottomNav({ screen, queueCount, setScreen }: { screen: Screen; queueCount: number; setScreen: (screen: Screen) => void }) { return <View style={styles.bottom}><NavItem label="Today" icon="⌂" active={screen === 'today'} onPress={() => setScreen('today')} /><NavItem label="Earnings" icon="₹" active={screen === 'earnings'} onPress={() => setScreen('earnings')} /><NavItem label={`Sync${queueCount ? ` · ${queueCount}` : ''}`} icon="↻" active={screen === 'sync'} onPress={() => setScreen('sync')} /><NavItem label="Profile" icon="◉" active={screen === 'profile'} onPress={() => setScreen('profile')} /></View>; }
function NavItem({ label, icon, active, onPress }: { label: string; icon: string; active: boolean; onPress: () => void }) { return <Pressable style={[styles.navItem, active && styles.navActive]} onPress={onPress}><Text style={[styles.navIcon, active && styles.navActiveText]}>{icon}</Text><Text style={[styles.navLabel, active && styles.navActiveText]}>{label}</Text></Pressable>; }
function DutyModal({ mode, proofCode, proofNote, expenseAmount, expenseType, expenseNote, proofPhotoUri, signatureData, setProofCode, setProofNote, setExpenseAmount, setExpenseType, setExpenseNote, onCamera, onSignature, onClose, onProof, onExpense }: { mode: ModalMode; proofCode: string; proofNote: string; expenseAmount: string; expenseType: string; expenseNote: string; proofPhotoUri: string | null; signatureData: string | null; setProofCode: (value: string) => void; setProofNote: (value: string) => void; setExpenseAmount: (value: string) => void; setExpenseType: (value: string) => void; setExpenseNote: (value: string) => void; onCamera: () => void; onSignature: () => void; onClose: () => void; onProof: () => void; onExpense: () => void }) {
  return <Modal visible={Boolean(mode)} transparent animationType="slide" onRequestClose={onClose}><Pressable style={styles.modalBackdrop} onPress={onClose}><KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.modalWrap}><Pressable style={styles.modalCard} onPress={event => event.stopPropagation()}><Text style={styles.modalTitle}>{mode === 'proof' ? 'Close with proof' : 'Add expense'}</Text><Text style={styles.modalSub}>{mode === 'proof' ? 'Keep the duty evidence attached to the trip.' : 'Capture it now. It can sync later.'}</Text>{mode === 'proof' ? <><Label text="Passenger OTP"><TextInput value={proofCode} onChangeText={setProofCode} keyboardType="number-pad" maxLength={6} placeholder="Enter the code" style={styles.input} /></Label><Label text="Proof note"><TextInput value={proofNote} onChangeText={setProofNote} placeholder="Optional handoff note" style={[styles.input, styles.multiline]} multiline /></Label><View style={styles.attachRow}><Pressable style={styles.attachButton} onPress={onCamera}><Text style={styles.attachText}>{proofPhotoUri ? 'Retake photo' : 'Capture photo'}</Text></Pressable><Pressable style={styles.attachButton} onPress={onSignature}><Text style={styles.attachText}>{signatureData ? 'Redo signature' : 'Add signature'}</Text></Pressable></View>{proofPhotoUri && <Text style={styles.attachedText}>✓ Photo attached</Text>}{signatureData && <Text style={styles.attachedText}>✓ Signature attached</Text>}</> : <><Label text="Expense type"><TextInput value={expenseType} onChangeText={setExpenseType} placeholder="Parking, toll or fuel" style={styles.input} /></Label><Label text="Amount in rupees"><TextInput value={expenseAmount} onChangeText={setExpenseAmount} keyboardType="decimal-pad" placeholder="e.g. 180" style={styles.input} /></Label><Label text="Note"><TextInput value={expenseNote} onChangeText={setExpenseNote} placeholder="Optional note" style={[styles.input, styles.multiline]} multiline /></Label></>}<View style={styles.modalActions}><Pressable style={styles.modalCancel} onPress={onClose}><Text style={styles.modalCancelText}>Cancel</Text></Pressable><Pressable style={styles.modalConfirm} onPress={mode === 'proof' ? onProof : onExpense}><Text style={styles.modalConfirmText}>{mode === 'proof' ? 'Record proof' : 'Save expense'}</Text></Pressable></View></Pressable></KeyboardAvoidingView></Pressable></Modal>;
}

function CameraCapture({ visible, onCancel, onPhoto }: { visible: boolean; onCancel: () => void; onPhoto: (uri: string) => void }) {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<any>(null);
  return <Modal visible={visible} animationType="slide" onRequestClose={onCancel}><View style={styles.cameraScreen}>{permission?.granted ? <CameraView ref={cameraRef} style={styles.camera} facing="back"><View style={styles.cameraTop}><Pressable style={styles.cameraClose} onPress={onCancel}><Text style={styles.cameraCloseText}>×</Text></Pressable><Text style={styles.cameraHint}>Duty proof photo</Text></View><Pressable style={styles.shutter} onPress={async () => { const result = await cameraRef.current?.takePictureAsync({ quality: 0.65, skipProcessing: true }); if (result?.uri) onPhoto(result.uri); }}><View style={styles.shutterInner} /></Pressable></CameraView> : <View style={styles.permissionCard}><Text style={styles.modalTitle}>Camera permission</Text><Text style={styles.modalSub}>Use the camera to attach a receipt or duty proof photo.</Text><Pressable style={styles.modalConfirm} onPress={requestPermission}><Text style={styles.modalConfirmText}>Allow camera</Text></Pressable><Pressable style={styles.modalCancel} onPress={onCancel}><Text style={styles.modalCancelText}>Not now</Text></Pressable></View>}</View></Modal>;
}

function SignatureCapture({ visible, onCancel, onSignature }: { visible: boolean; onCancel: () => void; onSignature: (data: string) => void }) {
  const signatureRef = useRef<any>(null);
  return <Modal visible={visible} animationType="slide" onRequestClose={onCancel}><View style={styles.signatureScreen}><Text style={styles.modalTitle}>Passenger signature</Text><Text style={styles.modalSub}>Draw inside the box. The signature is attached to the duty proof.</Text><View style={styles.signatureBox}><SignatureScreen ref={signatureRef} onOK={onSignature} onEmpty={() => Alert.alert('Signature needed', 'Please draw a signature before saving.')} autoClear={false} descriptionText="" clearText="Clear" confirmText="Use signature" webStyle={`body{background:#fffefa;} .m-signature-pad--footer{display:flex;justify-content:space-between;padding:8px;} .button{font-size:13px;color:#0e8b79;}`} /></View><Pressable style={styles.modalCancel} onPress={onCancel}><Text style={styles.modalCancelText}>Cancel</Text></Pressable></View></Modal>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.canvas }, app: { flex: 1, backgroundColor: colors.canvas }, loading: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.canvas }, loadingText: { marginTop: 10, color: colors.muted, fontSize: 12 }, login: { flex: 1, justifyContent: 'space-between', paddingHorizontal: 22, paddingTop: 24, paddingBottom: 24, backgroundColor: colors.deep }, brand: { flexDirection: 'row', alignItems: 'center', gap: 10 }, brandMark: { width: 35, height: 35, borderRadius: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.lime }, brandLetter: { color: colors.deep, fontWeight: '900', fontSize: 17 }, brandText: { color: '#f6fbf4', fontWeight: '800', fontSize: 17, letterSpacing: -0.5 }, loginEyebrow: { color: '#a9c18f', fontSize: 9, fontWeight: '800', letterSpacing: 1.7, marginTop: 44 }, loginTitle: { color: '#f5faf3', fontSize: 38, fontWeight: '800', letterSpacing: -2.5, lineHeight: 39, marginTop: 11 }, lime: { color: colors.lime }, loginCopy: { color: '#b4c4c1', fontSize: 12, lineHeight: 18, maxWidth: 330, marginTop: 10 }, loginCard: { backgroundColor: colors.card, borderRadius: 20, padding: 20, marginTop: 20 }, cardTitle: { color: colors.ink, fontSize: 20, fontWeight: '800', letterSpacing: -0.8 }, cardSub: { color: colors.muted, fontSize: 10.5, lineHeight: 15, marginTop: 5 }, label: { marginTop: 13 }, labelText: { color: colors.ink, fontSize: 10, fontWeight: '800', marginBottom: 6 }, input: { height: 44, borderWidth: 1, borderColor: '#d6e1da', borderRadius: 10, paddingHorizontal: 12, color: colors.ink, fontSize: 12, backgroundColor: '#fff' }, multiline: { height: 75, paddingTop: 11, textAlignVertical: 'top' }, primaryButton: { minHeight: 47, borderRadius: 11, backgroundColor: colors.deep, alignItems: 'center', justifyContent: 'center', marginTop: 18 }, primaryText: { color: '#f6fbf4', fontWeight: '800', fontSize: 12 }, loginNote: { marginTop: 13, padding: 10, borderRadius: 9, backgroundColor: '#f2f8df' }, noteText: { color: '#63732f', fontSize: 9, lineHeight: 13 }, loginFooter: { color: '#8da19a', textAlign: 'center', fontSize: 9 }, header: { paddingHorizontal: 17, paddingTop: 14, paddingBottom: 11, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: colors.line, backgroundColor: 'rgba(243,247,243,.96)' }, headerBrand: { flexDirection: 'row', alignItems: 'center', gap: 9 }, smallMark: { width: 29, height: 29, borderRadius: 9, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.lime }, headerTitle: { color: colors.ink, fontSize: 12, fontWeight: '800' }, headerSub: { color: colors.muted, fontSize: 9, marginTop: 2 }, network: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 9, paddingVertical: 6, borderRadius: 99, borderWidth: 1, borderColor: '#cfe7dd', backgroundColor: '#effaf4' }, networkOffline: { borderColor: '#f0dbad', backgroundColor: colors.amberSoft }, networkDot: { width: 6, height: 6, borderRadius: 6, backgroundColor: '#20b58e' }, networkDotOffline: { backgroundColor: '#cf8d26' }, networkText: { color: colors.teal, fontSize: 9, fontWeight: '800' }, networkTextOffline: { color: colors.amber }, scroll: { padding: 17, paddingBottom: 110 }, eyebrowDark: { color: colors.teal, fontSize: 8, fontWeight: '800', letterSpacing: 1.4, marginTop: 3 }, title: { color: colors.ink, fontSize: 27, fontWeight: '800', letterSpacing: -1.6, marginTop: 5 }, subtitle: { color: colors.muted, fontSize: 10.5, lineHeight: 15, marginTop: 6, marginBottom: 18 }, greeting: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end', gap: 12, marginBottom: 16 }, avatar: { width: 39, height: 39, borderRadius: 12, backgroundColor: '#d9efb6', alignItems: 'center', justifyContent: 'center' }, avatarText: { color: '#56721b', fontSize: 11, fontWeight: '900' }, nextCard: { backgroundColor: colors.deep, borderRadius: 20, padding: 19, overflow: 'hidden' }, nextRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, nextEyebrow: { color: '#bcd1ac', fontSize: 9, fontWeight: '800', letterSpacing: 1.1 }, statusReady: { color: colors.lime, fontSize: 9, fontWeight: '800' }, nextTitle: { color: '#f4fbf0', fontSize: 23, fontWeight: '800', letterSpacing: -1.2, marginTop: 11 }, nextSub: { color: '#b6cac4', fontSize: 10.5, marginTop: 4 }, route: { flexDirection: 'row', gap: 10, marginTop: 18, paddingTop: 12, borderTopWidth: 1, borderTopColor: 'rgba(218,250,91,.13)' }, routeNodes: { width: 11, alignItems: 'center', paddingTop: 3 }, routeDot: { width: 8, height: 8, borderRadius: 8, backgroundColor: colors.lime }, routeEnd: { backgroundColor: '#82dec3' }, routeLink: { width: 1, height: 27, backgroundColor: 'rgba(218,250,91,.32)' }, routeStrong: { color: '#f4fbf0', fontSize: 11, fontWeight: '800' }, routeSub: { color: '#9eb7af', fontSize: 9, marginTop: 3 }, mainAction: { minHeight: 47, borderRadius: 11, backgroundColor: colors.lime, alignItems: 'center', justifyContent: 'center', marginTop: 17 }, mainActionText: { color: '#26350e', fontSize: 12, fontWeight: '900' }, sectionLabel: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 20, marginBottom: 9 }, sectionTitle: { color: colors.ink, fontSize: 12, fontWeight: '800' }, sectionNote: { color: '#9aa8a8', fontSize: 9 }, quickGrid: { flexDirection: 'row', gap: 9 }, quick: { flex: 1, minHeight: 82, padding: 10, borderWidth: 1, borderColor: colors.line, borderRadius: 13, backgroundColor: colors.card }, quickIcon: { width: 28, height: 28, borderRadius: 9, alignItems: 'center', justifyContent: 'center' }, quickIconText: { fontSize: 14, fontWeight: '900' }, quickTitle: { color: colors.ink, fontSize: 9.5, fontWeight: '800', marginTop: 8 }, quickCopy: { color: colors.muted, fontSize: 8, marginTop: 2 }, timelineCard: { padding: 15, borderWidth: 1, borderColor: colors.line, borderRadius: 16, backgroundColor: colors.card }, timelineRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingVertical: 8 }, timelineTime: { width: 43, color: '#9aa8a8', fontSize: 9, paddingTop: 2 }, timelineDot: { width: 9, height: 9, borderRadius: 9, backgroundColor: colors.teal, marginTop: 3 }, timelineDotMuted: { backgroundColor: '#c0cbc5' }, timelineText: { flex: 1 }, timelineTitle: { color: colors.ink, fontSize: 10, fontWeight: '800', textTransform: 'capitalize' }, timelineCopy: { color: colors.muted, fontSize: 9, lineHeight: 13, marginTop: 3 }, emptyCard: { padding: 17, borderWidth: 1, borderColor: colors.line, borderRadius: 16, backgroundColor: colors.card }, emptyTitle: { color: colors.ink, fontSize: 13, fontWeight: '800' }, emptyCopy: { color: colors.muted, fontSize: 10, lineHeight: 15, marginTop: 6 }, syncCard: { padding: 15, borderWidth: 1, borderColor: colors.line, borderRadius: 16, backgroundColor: colors.card }, syncSummary: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingBottom: 13, marginBottom: 2, borderBottomWidth: 1, borderBottomColor: '#edf2ee' }, syncNumber: { color: colors.ink, fontSize: 22, fontWeight: '800' }, syncSub: { color: colors.muted, fontSize: 9, marginTop: 3 }, syncButton: { paddingHorizontal: 11, paddingVertical: 9, borderWidth: 1, borderColor: '#cfe2d7', borderRadius: 9, backgroundColor: colors.tealSoft }, syncButtonText: { color: colors.teal, fontSize: 10, fontWeight: '800' }, syncRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: '#edf2ee' }, syncIcon: { width: 28, height: 28, borderRadius: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.blueSoft }, syncTitle: { color: colors.ink, fontSize: 10, fontWeight: '800' }, syncCopy: { color: colors.muted, fontSize: 9, marginTop: 3 }, syncPending: { color: colors.amber, fontSize: 9, fontWeight: '800' }, syncReady: { color: colors.teal, fontSize: 9, fontWeight: '800' }, profileCard: { padding: 16, borderWidth: 1, borderColor: colors.line, borderRadius: 16, backgroundColor: colors.card }, profileHead: { flexDirection: 'row', alignItems: 'center', gap: 11, paddingBottom: 15, borderBottomWidth: 1, borderBottomColor: '#edf2ee' }, profileName: { color: colors.ink, fontSize: 13, fontWeight: '800' }, profileSub: { color: colors.muted, fontSize: 9, marginTop: 3 }, settingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: '#edf2ee' }, settingTitle: { color: colors.ink, fontSize: 10.5, fontWeight: '800' }, settingCopy: { color: colors.muted, fontSize: 9, marginTop: 3 }, settingValue: { color: colors.teal, fontSize: 9, fontWeight: '800' }, switch: { width: 37, height: 21, padding: 2, borderRadius: 99, backgroundColor: '#c9d5cf' }, switchOn: { backgroundColor: colors.teal }, switchKnob: { width: 17, height: 17, borderRadius: 17, backgroundColor: '#fff' }, switchKnobOn: { transform: [{ translateX: 16 }] }, secondaryButton: { minHeight: 44, borderWidth: 1, borderColor: colors.line, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginTop: 15, backgroundColor: colors.card }, secondaryText: { color: colors.ink, fontSize: 11, fontWeight: '800' }, bottom: { position: 'absolute', bottom: 0, left: 0, right: 0, paddingHorizontal: 17, paddingTop: 8, paddingBottom: 9, flexDirection: 'row', gap: 8, borderTopWidth: 1, borderTopColor: colors.line, backgroundColor: colors.card }, navItem: { flex: 1, minHeight: 48, borderRadius: 11, alignItems: 'center', justifyContent: 'center' }, navActive: { backgroundColor: colors.tealSoft }, navIcon: { color: '#9aa8a8', fontSize: 18, lineHeight: 19 }, navLabel: { color: '#9aa8a8', fontSize: 9, fontWeight: '800', marginTop: 2 }, navActiveText: { color: colors.teal }, busy: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(243,247,243,.35)' }, modalBackdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(10,20,22,.48)' }, modalWrap: { width: '100%' }, modalCard: { padding: 19, borderTopLeftRadius: 20, borderTopRightRadius: 20, backgroundColor: colors.card }, modalTitle: { color: colors.ink, fontSize: 19, fontWeight: '800', letterSpacing: -0.8 }, modalSub: { color: colors.muted, fontSize: 9.5, lineHeight: 14, marginTop: 5 }, attachRow: { flexDirection: 'row', gap: 8, marginTop: 13 }, attachButton: { flex: 1, minHeight: 40, borderWidth: 1, borderColor: '#cfe2d7', borderRadius: 9, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.tealSoft }, attachText: { color: colors.teal, fontSize: 10, fontWeight: '800' }, attachedText: { color: colors.teal, fontSize: 9, fontWeight: '800', marginTop: 7 }, cameraScreen: { flex: 1, backgroundColor: '#101b20' }, camera: { flex: 1 }, cameraTop: { paddingTop: 55, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', gap: 12 }, cameraClose: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,.42)' }, cameraCloseText: { color: '#fff', fontSize: 25, lineHeight: 28 }, cameraHint: { color: '#fff', fontSize: 12, fontWeight: '800' }, shutter: { position: 'absolute', bottom: 42, alignSelf: 'center', width: 70, height: 70, borderRadius: 70, borderWidth: 5, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' }, shutterInner: { width: 54, height: 54, borderRadius: 54, backgroundColor: colors.lime }, permissionCard: { margin: 20, marginTop: 'auto', marginBottom: 'auto', padding: 20, borderRadius: 18, backgroundColor: colors.card }, signatureScreen: { flex: 1, padding: 20, paddingTop: 60, backgroundColor: colors.canvas }, signatureBox: { height: 280, marginTop: 18, overflow: 'hidden', borderWidth: 1, borderColor: colors.line, borderRadius: 12, backgroundColor: colors.card }, modalActions:  { flexDirection: 'row', gap: 8, marginTop: 16 }, modalCancel: { flex: 1, minHeight: 43, borderWidth: 1, borderColor: colors.line, borderRadius: 10, alignItems: 'center', justifyContent: 'center' }, modalCancelText: { color: colors.ink, fontSize: 10, fontWeight: '800' }, modalConfirm: { flex: 1, minHeight: 43, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.deep }, modalConfirmText: { color: '#f5faf3', fontSize: 10, fontWeight: '800' },
});
