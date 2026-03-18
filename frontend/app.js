/* Trip Agent - Web UI */

const API_BASE = window.location.origin + '/a2a/';
const API_PLANS = window.location.origin + '/api';
const STORAGE_KEY = 'trip-agent-form';
const PLANS_STORAGE_KEY = 'trip-agent-plans';
const USER_ID_KEY = 'trip-agent-user-id';

function getUserId() {
  return localStorage.getItem(USER_ID_KEY) || null;
}

function setUserId(uid) {
  if (uid) localStorage.setItem(USER_ID_KEY, uid);
}

async function ensureUserId() {
  let uid = getUserId();
  if (uid) return uid;
  try {
    const r = await fetch(`${API_PLANS}/users/register`, { method: 'POST' });
    if (!r.ok) throw new Error('Register failed');
    const j = await r.json();
    uid = j.user_id;
    if (uid) {
      setUserId(uid);
      return uid;
    }
  } catch (_) { /* ignore */ }
  return null;
}

async function plansApi(method, path, body) {
  const uid = await ensureUserId();
  if (!uid) return { error: 'No user id' };
  const opts = { method, headers: { 'X-User-Id': uid, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API_PLANS}${path}`, opts);
  const j = r.ok ? await r.json().catch(() => ({})) : null;
  return { ok: r.ok, status: r.status, data: j };
}

function loadFormFromStorage() {
  try {
    const s = localStorage.getItem(STORAGE_KEY);
    if (!s) return;
    const data = JSON.parse(s);
    const form = $('#travel-form');
    if (!form) return;
    const set = (name, v) => { const el = form[name]; if (el && v != null) el.value = String(v); };
    const setCheck = (name, v) => { const el = form[name]; if (el) el.checked = !!v; };
    if (data.trip_type) set('trip_type', data.trip_type);
    if (data.origin) set('origin', data.origin);
    if (data.destination) set('destination', data.destination);
    if (data.start_date) set('start_date', data.start_date);
    if (data.end_date) set('end_date', data.end_date);
    if (data.travelers_male != null) set('travelers_male', data.travelers_male);
    if (data.travelers_female != null) set('travelers_female', data.travelers_female);
    if (data.travelers_children != null) set('travelers_children', data.travelers_children);
    if (data.date_flexibility_days != null) set('date_flexibility_days', data.date_flexibility_days);
    if (data.local_transport) set('local_transport', data.local_transport);
    if (data.accommodation_priority_1) set('accommodation_priority_1', data.accommodation_priority_1);
    if (data.accommodation_priority_2) set('accommodation_priority_2', data.accommodation_priority_2);
    if (data.accommodation_priority_3) set('accommodation_priority_3', data.accommodation_priority_3);
    if (data.seat_class) set('seat_class', data.seat_class);
    if (data.pace) set('pace', data.pace);
    if (data.budget_level) set('budget_level', data.budget_level);
    if (data.mileage_balance != null) set('mileage_balance', data.mileage_balance);
    if (data.mileage_program != null) set('mileage_program', data.mileage_program);
    setCheck('use_miles', data.use_miles);
    if (data.origin_airport_code) state.origin_airport_code = data.origin_airport_code;
    if (data.destination_airport_code) state.destination_airport_code = data.destination_airport_code;

    if (data.multi_cities) {
      state.multi_cities = data.multi_cities;
    }
  } catch (_) { /* ignore */ }
}

function saveFormToStorage() {
  try {
    const form = $('#travel-form');
    if (!form) return;
    updateStateFromMultiCityDOM();
    const data = {
      trip_type: form.trip_type?.value || 'round_trip',
      origin: form.origin?.value,
      destination: form.destination?.value,
      start_date: form.start_date?.value,
      end_date: form.end_date?.value,
      travelers_male: form.travelers_male?.value,
      travelers_female: form.travelers_female?.value,
      travelers_children: form.travelers_children?.value,
      date_flexibility_days: form.date_flexibility_days?.value,
      local_transport: form.local_transport?.value,
      accommodation_priority_1: form.accommodation_priority_1?.value,
      accommodation_priority_2: form.accommodation_priority_2?.value,
      accommodation_priority_3: form.accommodation_priority_3?.value,
      seat_class: form.seat_class?.value,
      pace: form.pace?.value,
      budget_level: form.budget_level?.value,
      mileage_balance: form.mileage_balance?.value,
      mileage_program: form.mileage_program?.value,
      use_miles: form.use_miles?.checked,
      origin_airport_code: state.origin_airport_code,
      destination_airport_code: state.destination_airport_code,
      multi_cities: state.multi_cities,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (_) { /* ignore */ }
}

/* === 계획 저장/불러오기 (파일처럼 편집·저장·열기) === */
function getFormDataForPlan() {
  const form = $('#travel-form');
  if (!form) return {};
  updateStateFromMultiCityDOM();
  return {
    trip_type: form.trip_type?.value || 'round_trip',
    origin: form.origin?.value,
    destination: form.destination?.value,
    start_date: form.start_date?.value,
    end_date: form.end_date?.value,
    travelers_male: form.travelers_male?.value,
    travelers_female: form.travelers_female?.value,
    travelers_children: form.travelers_children?.value,
    date_flexibility_days: form.date_flexibility_days?.value,
    local_transport: form.local_transport?.value,
    accommodation_priority_1: form.accommodation_priority_1?.value,
    accommodation_priority_2: form.accommodation_priority_2?.value,
    accommodation_priority_3: form.accommodation_priority_3?.value,
    seat_class: form.seat_class?.value,
    pace: form.pace?.value,
    budget_level: form.budget_level?.value,
    mileage_balance: form.mileage_balance?.value,
    mileage_program: form.mileage_program?.value,
    use_miles: form.use_miles?.checked,
    origin_airport_code: state.origin_airport_code,
    destination_airport_code: state.destination_airport_code,
    multi_cities: state.multi_cities,
  };
}

function setFormFromPlanData(data) {
  const form = $('#travel-form');
  if (!form || !data) return;
  const set = (name, v) => { const el = form[name]; if (el && v != null) el.value = String(v); };
  const setCheck = (name, v) => { const el = form[name]; if (el) el.checked = !!v; };
  if (data.trip_type) set('trip_type', data.trip_type);
  if (data.origin != null) set('origin', data.origin);
  if (data.destination != null) set('destination', data.destination);
  if (data.start_date != null) set('start_date', data.start_date);
  if (data.end_date != null) set('end_date', data.end_date);
  if (data.travelers_male != null) set('travelers_male', data.travelers_male);
  if (data.travelers_female != null) set('travelers_female', data.travelers_female);
  if (data.travelers_children != null) set('travelers_children', data.travelers_children);
  if (data.date_flexibility_days != null) set('date_flexibility_days', data.date_flexibility_days);
  if (data.local_transport != null) set('local_transport', data.local_transport);
  if (data.accommodation_priority_1 != null) set('accommodation_priority_1', data.accommodation_priority_1);
  if (data.accommodation_priority_2 != null) set('accommodation_priority_2', data.accommodation_priority_2);
  if (data.accommodation_priority_3 != null) set('accommodation_priority_3', data.accommodation_priority_3);
  if (data.seat_class != null) set('seat_class', data.seat_class);
  if (data.pace != null) set('pace', data.pace);
  if (data.budget_level != null) set('budget_level', data.budget_level);
  if (data.mileage_balance != null) set('mileage_balance', data.mileage_balance);
  if (data.mileage_program != null) set('mileage_program', data.mileage_program);
  setCheck('use_miles', data.use_miles);
  if (data.origin_airport_code != null) state.origin_airport_code = data.origin_airport_code;
  if (data.destination_airport_code != null) state.destination_airport_code = data.destination_airport_code;
  if (Array.isArray(data.multi_cities)) state.multi_cities = data.multi_cities;
  initTripTypeUI();
  if (state.multi_cities?.length) renderMultiCityLegs();
}

function getFullPlanState() {
  return {
    formData: getFormDataForPlan(),
    travelInput: state.travelInput,
    trip_type: state.trip_type,
    multi_cities: state.multi_cities,
    origin_airport_code: state.origin_airport_code,
    destination_airport_code: state.destination_airport_code,
    flights: state.flights,
    flightsByLeg: state.flightsByLeg || {},
    currentFlights: state.currentFlights,
    flightWarnings: state.flightWarnings,
    selectedOutboundFlight: state.selectedOutboundFlight,
    selectedReturnFlight: state.selectedReturnFlight,
    selectedMultiCityFlights: state.selectedMultiCityFlights,
    selectedFlight: state.selectedFlight,
    flightLeg: state.flightLeg,
    itineraries: state.itineraries,
    selectedItinerary: state.selectedItinerary,
    accommodations: state.accommodations,
    selectedAccommodation: state.selectedAccommodation,
    localTransport: state.localTransport,
    selectedLocalTransport: state.selectedLocalTransport,
  };
}

function loadPlanIntoState(data) {
  if (!data) return;
  if (data.formData) setFormFromPlanData(data.formData);
  state.travelInput = data.travelInput ?? null;
  state.trip_type = data.trip_type ?? 'round_trip';
  state.multi_cities = Array.isArray(data.multi_cities) ? data.multi_cities : [];
  state.origin_airport_code = data.origin_airport_code ?? null;
  state.destination_airport_code = data.destination_airport_code ?? null;
  state.flights = Array.isArray(data.flights) ? data.flights : [];
  state.flightsByLeg = data.flightsByLeg && typeof data.flightsByLeg === 'object' ? data.flightsByLeg : {};
  state.currentFlights = Array.isArray(data.currentFlights) ? data.currentFlights : (state.flights.length ? state.flights : null);
  state.flightWarnings = Array.isArray(data.flightWarnings) ? data.flightWarnings : [];
  state.selectedOutboundFlight = data.selectedOutboundFlight ?? null;
  state.selectedReturnFlight = data.selectedReturnFlight ?? null;
  state.selectedMultiCityFlights = Array.isArray(data.selectedMultiCityFlights) ? data.selectedMultiCityFlights : [];
  state.selectedFlight = data.selectedFlight ?? null;
  state.flightLeg = data.flightLeg ?? 'outbound';
  state.itineraries = Array.isArray(data.itineraries) ? data.itineraries : [];
  state.selectedItinerary = data.selectedItinerary ?? null;
  state.accommodations = Array.isArray(data.accommodations) ? data.accommodations : [];
  state.selectedAccommodation = data.selectedAccommodation ?? null;
  state.localTransport = Array.isArray(data.localTransport) ? data.localTransport : [];
  state.selectedLocalTransport = data.selectedLocalTransport ?? null;
}

function getSavedPlans() {
  try {
    const s = localStorage.getItem(PLANS_STORAGE_KEY);
    if (!s) return [];
    const arr = JSON.parse(s);
    return Array.isArray(arr) ? arr : [];
  } catch (_) { return []; }
}

function savePlansToStorage(plans) {
  try {
    localStorage.setItem(PLANS_STORAGE_KEY, JSON.stringify(plans));
  } catch (_) { /* ignore */ }
}

async function getSavedPlansFromServer() {
  const res = await plansApi('GET', '/plans');
  if (!res.ok || !res.data?.plans) return [];
  return res.data.plans.map(p => ({ ...p, data: null }));
}

async function savePlan(name, isSaveAs = false) {
  const planState = getFullPlanState();
  const uid = await ensureUserId();
  if (!uid) {
    alert('서버 연결을 위해 연결 코드를 먼저 확인해 주세요.');
    return false;
  }

  const finalName = name || state.currentPlanName || prompt('계획 이름을 입력하세요 (예: 3월 오사카 여행):', getDefaultPlanName());
  if (!finalName || !finalName.trim()) return false;

  const isUpdate = state.currentPlanId && !isSaveAs;
  const path = isUpdate ? `/plans/${state.currentPlanId}` : '/plans';
  const method = isUpdate ? 'PUT' : 'POST';
  const body = isUpdate ? { name: finalName.trim(), data: planState } : { name: finalName.trim(), data: planState, id: state.currentPlanId || undefined };

  const res = await plansApi(method, path, body);
  if (!res.ok) {
    alert(res.data?.error || '저장에 실패했습니다.');
    return false;
  }

  state.currentPlanId = res.data.id;
  state.currentPlanName = finalName.trim();
  return true;
}

function getDefaultPlanName() {
  const ti = state.travelInput;
  const dest = ti?.destination || $('#travel-form')?.destination?.value || '';
  const start = ti?.start_date || $('#travel-form')?.start_date?.value || '';
  if (dest || start) return `${dest || '여행'} ${(start || '').slice(0, 7)}`.trim();
  return `여행 계획 ${new Date().toLocaleDateString('ko-KR')}`;
}

async function openPlan(planId) {
  const res = await plansApi('GET', `/plans/${planId}`);
  let plan = null;
  if (res.ok && res.data?.data) {
    plan = res.data;
  } else {
    const local = getSavedPlans().find(p => p.id === planId);
    if (local?.data) plan = local;
  }
  if (!plan || !plan.data) {
    alert('계획을 불러올 수 없습니다.');
    return;
  }
  loadPlanIntoState(plan.data);
  state.currentPlanId = plan.id;
  state.currentPlanName = plan.name;
  saveFormToStorage();
  renderPlanUI();

  const step = resolveCurrentStep();
  const sectionId = STEP_TO_SECTION[step] || 'step-input';
  show(sectionId, true);
}

function resolveCurrentStep() {
  if (state.selectedAccommodation) return 'confirm';
  if (state.accommodations?.length) return 'accommodation';
  if (state.selectedItinerary && !state.accommodations?.length) return 'itineraries';
  if (state.itineraries?.length) return 'itineraries';
  if (state.selectedLocalTransport || state.localTransport?.length) return 'rental';
  if (buildSelectedFlight()) return state.localTransport?.length ? 'rental' : 'rental';
  if (state.flights?.length || (state.flightsByLeg && Object.keys(state.flightsByLeg).length)) return 'flights';
  return 'input';
}

async function deletePlan(planId) {
  const res = await plansApi('DELETE', `/plans/${planId}`);
  if (!res.ok) alert(res.data?.error || '삭제에 실패했습니다.');
  const plans = getSavedPlans().filter(p => p.id !== planId);
  savePlansToStorage(plans);
  if (state.currentPlanId === planId) {
    state.currentPlanId = null;
    state.currentPlanName = null;
    renderPlanUI();
  }
}

function newPlan() {
  state.currentPlanId = null;
  state.currentPlanName = null;
  state.travelInput = null;
  state.trip_type = 'round_trip';
  state.multi_cities = [];
  state.origin_airport_code = null;
  state.destination_airport_code = null;
  state.flights = [];
  state.flightsByLeg = {};
  state.currentFlights = null;
  state.selectedOutboundFlight = null;
  state.selectedReturnFlight = null;
  state.selectedMultiCityFlights = [];
  state.selectedFlight = null;
  state.flightLeg = 'outbound';
  state.itineraries = [];
  state.selectedItinerary = null;
  state.accommodations = [];
  state.selectedAccommodation = null;
  state.localTransport = [];
  state.selectedLocalTransport = null;
  state.flightWarnings = [];
  loadFormFromStorage();
  initTripTypeUI();
  renderPlanUI();
  show('step-input');
}

function renderPlanUI() {
  const bar = $('#plan-toolbar');
  if (!bar) return;
  const nameEl = $('#current-plan-name');
  if (nameEl) nameEl.textContent = state.currentPlanName ? `"${state.currentPlanName}"` : '(저장 안 함)';
}

let state = {
  travelInput: null,
  trip_type: 'round_trip',
  multi_cities: [],
  origin_airport_code: null,
  destination_airport_code: null,
  flights: [],
  flightsByLeg: {},
  selectedOutboundFlight: null,
  selectedReturnFlight: null,
  selectedMultiCityFlights: [],
  selectedFlight: null,
  flightLeg: 'outbound',
  itineraries: [],
  selectedItinerary: null,
  accommodations: [],
  selectedAccommodation: null,
  localTransport: [],
  selectedLocalTransport: null,
  currentPlanId: null,
  currentPlanName: null,
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

const STEP_IDS = {
  'step-input': 'input',
  'step-origin-airports': 'input',
  'step-destination-airports': 'input',
  'step-flights': 'flights',
  'step-rental': 'rental',
  'step-itineraries': 'itineraries',
  'step-accommodation': 'accommodation',
  'step-confirm': 'booking',
};

const STEP_TO_SECTION = {
  input: 'step-input',
  flights: 'step-flights',
  rental: 'step-rental',
  itineraries: 'step-itineraries',
  accommodation: 'step-accommodation',
  confirm: 'step-confirm',
  booking: 'step-confirm',
};

function show(id, fromStepClick = false) {
  $$('section').forEach(s => s.classList.add('hidden'));
  const el = $(`#${id}`);
  if (el) el.classList.remove('hidden');
  const step = STEP_IDS[id];
  if (step) {
    $$('#step-indicator .step-node').forEach(node => {
      node.classList.toggle('active', node.dataset.step === step);
      node.classList.remove('completed');
    });
    updateStepCompletedState();
    if (fromStepClick && step) {
      refreshStepView(step);
    }
  }
  if (id === 'step-flights') updateFlightNextButtonLabel();
}

function updateStepCompletedState() {
  const nodes = $$('#step-indicator .step-node');
  const steps = ['input', 'flights', 'rental', 'itineraries', 'accommodation', 'confirm', 'booking'];
  steps.forEach((s, i) => {
    const node = nodes[i];
    if (!node) return;
    const hasData = s === 'input' && state.travelInput
      || s === 'flights' && buildSelectedFlight()
      || s === 'rental' && (state.localTransport?.length > 0 || state.selectedLocalTransport)
      || s === 'itineraries' && (state.itineraries?.length > 0 || state.selectedItinerary)
      || s === 'accommodation' && (state.accommodations?.length > 0 || state.selectedAccommodation)
      || (s === 'confirm' || s === 'booking') && state.selectedAccommodation;
    if (hasData && !node.classList.contains('active')) {
      node.classList.add('completed');
    }
  });
}

function refreshStepView(step) {
  if (step === 'input' && state.travelInput) {
    const form = $('#travel-form');
    if (form && state.travelInput) {
      const ti = state.travelInput;
      const setVal = (el, v) => { if (el && v != null) el.value = String(v); };
      setVal(form.origin, ti.origin);
      setVal(form.destination, ti.destination);
      setVal($('#start_date_input') || form.start_date, ti.start_date);
      setVal($('#end_date_input') || form.end_date, ti.end_date);
      setVal($('#trip_type_select') || form.trip_type, ti.trip_type);
      if (ti.travelers) {
        setVal(form.travelers_male, ti.travelers?.male);
        setVal(form.travelers_female, ti.travelers?.female);
        setVal(form.travelers_children, ti.travelers?.children);
      }
      initTripTypeUI();
      if (ti.trip_type === 'multi_city' && (ti.multi_cities || state.multi_cities)?.length) {
        state.multi_cities = ti.multi_cities || state.multi_cities;
        renderMultiCityLegs();
      }
      saveFormToStorage();
    }
  }
  if (step === 'flights') {
    const sf = buildSelectedFlight();
    const flightsToShow = state.currentFlights || state.flights || (state.trip_type === 'multi_city' ? Object.values(state.flightsByLeg || {}).flat() : []);
    if (sf && flightsToShow.length) {
      renderFlights(flightsToShow, state.flightWarnings || []);
      showFlightSummaryForEdit(sf);
    } else if (flightsToShow.length) {
      renderFlights(flightsToShow, state.flightWarnings || []);
      $('#flights-list').classList.remove('hidden');
      $('#flight-sort-bar').classList.remove('hidden');
      $('#selected-flight-summary').classList.add('hidden');
    }
  }
  if (step === 'rental' && state.localTransport?.length) {
    renderRentalOptions(state.localTransport);
  }
  if (step === 'itineraries' && state.itineraries?.length) {
    renderItineraries(state.itineraries);
  }
  if (step === 'accommodation' && state.accommodations?.length) {
    renderAccommodations(state.accommodations);
    const ltEl = $('#local-transport-info');
    if (ltEl) ltEl.innerHTML = state.localTransport?.length
      ? `<h4>현지 이동</h4><pre>${JSON.stringify(state.localTransport, null, 2)}</pre>`
      : '';
  }
}

function formatFlightDetailForSummary(f, label, hidePrice, isRoundTripTotal) {
  const destL = f.destination_label ? `${f.destination || ''} (${f.destination_label})` : (f.destination || '');
  const route = `${f.origin || ''} → ${destL}`;
  const dep = fmtFlightDateTime(f.departure);
  const arr = fmtFlightDateTime(f.arrival);
  const dur = f.duration_hours ? `약 ${f.duration_hours}시간` : '';
  const priceStr = hidePrice ? '' : (f.price_krw ? f.price_krw.toLocaleString() + '원' : (f.miles_required || 0) + '마일');
  const price = priceStr ? (priceStr + (isRoundTripTotal ? ' (왕복)' : '')) : '';
  let segHtml = '';
  if (f.segments && f.segments.length > 0) {
    segHtml = f.segments.map((seg, si) => {
      const dAirport = seg.departure_airport?.name || seg.departure_airport?.id || '';
      const aAirport = seg.arrival_airport?.name || seg.arrival_airport?.id || '';
      const dTime = fmtFlightDateTime(seg.departure_airport?.time?.substring(0, 19) || '');
      const aTime = fmtFlightDateTime(seg.arrival_airport?.time?.substring(0, 19) || '');
      const segDur = seg.duration ? Math.round(seg.duration / 60) + 'h ' + (seg.duration % 60) + 'm' : '';
      return `<div class="flight-seg">${seg.airline} ${seg.flight_number} ${dTime} ${dAirport} → ${aTime} ${aAirport} ${segDur ? '(' + segDur + ')' : ''}</div>`;
    }).join('');
  }
  return `
    <div class="selected-flight-card">
      <div class="selected-flight-label">${label}</div>
      <div class="selected-flight-main">${f.airline || '항공사'} ${f.flight_number || ''} · ${route}</div>
      <div class="selected-flight-meta">출발 ${dep} · 도착 ${arr} ${dur ? '· 비행 ' + dur : ''}</div>
      ${price ? `<div class="selected-flight-price">${price}</div>` : ''}
      ${segHtml ? '<div class="selected-flight-segments">' + segHtml + '</div>' : ''}
    </div>`;
}

function showFlightSummaryForEdit(sf) {
  const summary = $('#selected-flight-summary');
  const summaryText = $('#selected-flight-text');
  const list = $('#flights-list');
  const sortBar = $('#flight-sort-bar');
  if (!summary || !summaryText) return;
  list.classList.add('hidden');
  sortBar.classList.add('hidden');
  const isRoundTrip = !!(sf.outbound && sf.return);
  let html = '<div class="selected-flight-header">✅ 선택완료</div>';
  if (sf.outbound) {
    html += formatFlightDetailForSummary(sf.outbound, '출국편', false, isRoundTrip);
  }
  if (sf.return) {
    html += formatFlightDetailForSummary(sf.return, '귀국편', isRoundTrip);
  }
  if (sf.legs?.length) {
    html = '<div class="selected-flight-header">✅ 선택완료</div>' + sf.legs.map((f, i) =>
      formatFlightDetailForSummary(f, `구간 ${i + 1}`)
    ).join('');
  }
  summaryText.innerHTML = html || '선택된 항공편 없음';
  summary.classList.remove('hidden');
  const nextBtn = $('#btn-next-flights');
  if (nextBtn) {
    nextBtn.disabled = false;
    nextBtn.style.opacity = '1';
    nextBtn.style.cursor = 'pointer';
  }
  updateFlightNextButtonLabel();
}

function navigateToStep(stepName) {
  const sectionId = STEP_TO_SECTION[stepName];
  if (!sectionId) return;
  show(sectionId, true);
}

function showError(msg) {
  $('#error-message').textContent = msg;
  show('error');
}

async function callAgent(payload) {
  const resp = await fetch(API_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: crypto.randomUUID(),
      method: 'message/send',
      params: {
        message: {
          role: 'user',
          parts: [{ kind: 'text', text: JSON.stringify(payload) }],
          messageId: crypto.randomUUID().replace(/-/g, ''),
        },
      },
    }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.error) throw new Error(data.error.message || 'Agent error');
  const r = data.result;
  let msg = r?.message?.parts?.[0]?.text ?? r?.parts?.[0]?.text;
  if (!msg && r?.parts?.[0]) {
    const p = r.parts[0];
    msg = p.text ?? p.content ?? (typeof p === 'string' ? p : null);
  }
  if (!msg && r?.artifacts?.[0]?.parts?.[0])
    msg = r.artifacts[0].parts[0].text ?? r.artifacts[0].parts[0].content;
  if (!msg) {
    const hint = r ? JSON.stringify(r).slice(0, 200) : 'empty';
    throw new Error('No response. Backend returned: ' + hint);
  }
  function extractText(str) {
    if (typeof str !== 'string') return str;
    try {
      const o = JSON.parse(str);
      if (o && typeof o === 'object') {
        const inner = o.parts?.[0]?.text ?? o.message?.parts?.[0]?.text;
        if (inner) return extractText(inner);
        return str;
      }
    } catch { /* not JSON */ }
    return str;
  }
  const content = extractText(msg);
  try {
    return JSON.parse(content);
  } catch {
    return { raw: content };
  }
}

function buildTravelInput() {
  const form = $('#travel-form');
  const p1 = form.accommodation_priority_1?.value || 'hotel';
  const p2 = form.accommodation_priority_2?.value;
  const p3 = form.accommodation_priority_3?.value;
  const accommodation_priority = [p1];
  if (p2 && p2 !== p1) accommodation_priority.push(p2);
  if (p3 && p3 !== p1 && p3 !== p2) accommodation_priority.push(p3);

  const flexEl = form.elements?.date_flexibility_days ?? form.date_flexibility_days;
  const flex = parseInt(flexEl?.value ?? '', 10);
  const male = parseInt(form.travelers_male?.value, 10) || 0;
  const female = parseInt(form.travelers_female?.value, 10) || 0;
  const children = parseInt(form.travelers_children?.value, 10) || 0;
  const trip_type = form.trip_type?.value || 'round_trip';
  let multi_cities = [];
  if (trip_type === 'multi_city') {
    updateStateFromMultiCityDOM();
    multi_cities = state.multi_cities;
  }

  const input = {
    trip_type: trip_type,
    origin: trip_type === 'multi_city' && multi_cities.length > 0 ? multi_cities[0].origin : form.origin.value,
    destination: trip_type === 'multi_city' && multi_cities.length > 0 ? multi_cities[multi_cities.length - 1].destination : form.destination.value,
    start_date: trip_type === 'multi_city' && multi_cities.length > 0 ? multi_cities[0].date : form.start_date.value,
    end_date: trip_type === 'round_trip' ? form.end_date?.value : (trip_type === 'multi_city' && multi_cities.length > 0 ? multi_cities[multi_cities.length - 1].date : null) || form.start_date?.value || form.end_date?.value,
    multi_cities: trip_type === 'multi_city' ? multi_cities : null,
    date_flexibility_days: isNaN(flex) || flex <= 0 ? null : flex,
    local_transport: form.local_transport.value,
    accommodation_type: p1,
    accommodation_priority,
    seat_class: form.seat_class.value,
    use_miles: form.use_miles.checked,
    mileage_balance: parseInt(form.mileage_balance.value) || 0,
    mileage_program: form.mileage_program.value || null,
    preference: {
      pace: form.pace.value,
      budget_level: form.budget_level.value,
    },
    travelers: { male: Math.max(0, male), female: Math.max(0, female), children: Math.max(0, children) },
  };
  if (state.origin_airport_code)
    input.origin_airport_code = state.origin_airport_code;
  if (state.destination_airport_code)
    input.destination_airport_code = state.destination_airport_code;
  // 마일리지 선호 시 다중 공항 검색: 직항 있는 공항 우선 (돌로미티+Skypass → MXP 최우선)
  const mileageKey = typeof normalizeMileageProgram === 'function' ? normalizeMileageProgram(form.mileage_program?.value) : '';
  if (mileageKey && needDestAirport()) {
    const originCode = state.origin_airport_code || form.origin?.value?.trim() || '';
    const airports = getDestAirportsForOrigin(originCode, form.destination?.value?.trim(), {
      useMiles: form.use_miles?.checked,
      mileageProgram: form.mileage_program?.value,
    });
    if (airports && airports.length > 1)
      input.destination_airports = airports.map(a => a.code);
  }
  return input;
}

function needOriginAirport() {
  const form = $('#travel-form');
  const type = form.trip_type?.value;
  let origin = '';
  if (type === 'multi_city' && state.multi_cities && state.multi_cities.length > 0) {
    origin = state.multi_cities[0].origin.trim();
  } else {
    origin = form.origin?.value?.trim() || '';
  }
  return origin && !isAirportCode(origin) && getAirportsForCity(origin);
}

function needDestAirport() {
  const form = $('#travel-form');
  const type = form.trip_type?.value;
  let dest = '';
  if (type === 'multi_city' && state.multi_cities && state.multi_cities.length > 0) {
    dest = state.multi_cities[state.multi_cities.length - 1].destination.trim();
  } else {
    dest = form.destination?.value?.trim() || '';
  }
  return dest && !isAirportCode(dest) && getAirportsForCity(dest);
}

function renderOriginAirports() {
  const origin = $('#travel-form').origin?.value?.trim() || '';
  const airports = getAirportsForCity(origin) || [];
  const list = $('#origin-airports-list');
  list.innerHTML = airports.map(a => `
    <div class="airport-item" data-code="${a.code}">
      <span><span class="code">${a.code}</span> <span class="name">${a.name}</span></span>
      <span>접근 ${a.drive_hours}h 이내</span>
    </div>
  `).join('');
  list.querySelectorAll('.airport-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.airport-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.origin_airport_code = el.dataset.code;
      saveFormToStorage();
    });
  });
}

function renderDestAirports() {
  const form = $('#travel-form');
  const dest = form.destination?.value?.trim() || '';
  const originCode = state.origin_airport_code || form.origin?.value?.trim() || '';
  const options = {
    useMiles: form.use_miles?.checked ?? false,
    mileageProgram: form.mileage_program?.value?.trim() || '',
  };
  const airports = getDestAirportsForOrigin(originCode, dest, options) || getAirportsForCity(dest) || [];
  const info = (typeof FLIGHT_INFO !== 'undefined' && FLIGHT_INFO[originCode]) || {};
  const mileageKey = typeof normalizeMileageProgram === 'function' ? normalizeMileageProgram(options.mileageProgram) : '';
  const list = $('#destination-airports-list');
  const sortedCodes = airports.map(a => a.code);
  list.innerHTML = airports.map((a, i) => {
    const fa = info[a.code] || {};
    const badges = [];
    if (fa.direct) badges.push('<span class="airport-badge direct">직항</span>');
    if (mileageKey && fa.mileage?.includes(mileageKey)) badges.push('<span class="airport-badge mileage">마일리지</span>');
    if (mileageKey && fa.direct && fa.mileage?.includes(mileageKey) && i === 0)
      badges.push('<span class="airport-badge recommend">권장</span>');
    return `
    <div class="airport-item" data-code="${a.code}">
      <span><span class="code">${a.code}</span> <span class="name">${a.name}</span> ${badges.join('')}</span>
      ${fa.hours ? `<span class="airport-meta">약 ${fa.hours}h</span>` : ''}
    </div>
  `;
  }).join('');
  list.querySelectorAll('.airport-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.airport-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.destination_airport_code = el.dataset.code;
      saveFormToStorage();
    });
  });
}

async function doFlightSearch(leg) {
  state.travelInput = buildTravelInput();
  state.trip_type = state.travelInput?.trip_type || $('#trip_type_select')?.value || 'round_trip';
  state.multi_cities = state.travelInput?.multi_cities || state.multi_cities || [];
  state.flightLeg = leg || (state.trip_type === 'multi_city' ? 'multi_city_0' : 'outbound');
  const payload = { ...state.travelInput };
  if (state.trip_type === 'round_trip' || state.trip_type === 'one_way') {
    payload.flight_leg = state.flightLeg;
  }
  if (state.trip_type === 'multi_city') {
    payload.flight_leg = state.flightLeg;
    if (state.selectedMultiCityFlights?.length > 0) {
      payload.selected_multi_city_flights = state.selectedMultiCityFlights;
    }
  }
  if (state.flightLeg === 'return' && state.selectedOutboundFlight) {
    payload.selected_outbound_flight = state.selectedOutboundFlight;
  }
  show('loading');
  try {
    let data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    let flights = Array.isArray(data) ? data : (data?.flights || []);
    if (!Array.isArray(flights) && typeof data === 'object' && !data.step) {
      flights = [data];
    }
    const warnings = data?.warnings || [];
    state.flights = flights;
    state.flightsByLeg[state.flightLeg] = flights;
    state.flightWarnings = warnings;
    renderFlights(flights, warnings);
    if (state.flightLeg === 'return' || (state.trip_type === 'multi_city' && state.flightLeg !== 'multi_city_0')) {
      $('#flights-list').classList.remove('hidden');
      $('#flight-sort-bar').classList.remove('hidden');
      $('#selected-flight-summary').classList.add('hidden');
      if (state.flightLeg === 'return') state.selectedReturnFlight = null;
    }
    updateFlightNextButtonLabel();
    show('step-flights');
  } catch (err) {
    showError(err.message);
  }
}

$('#travel-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const startVal = $('#travel-form').start_date?.value;
  const endVal = $('#travel-form').end_date?.value;
  if (startVal && endVal && endVal < startVal) {
    alert('귀환일은 출발일 이후로 선택해 주세요.');
    return;
  }

  if (needOriginAirport() && !state.origin_airport_code) {
    renderOriginAirports();
    show('step-origin-airports');
    return;
  }
  if (needDestAirport() && !state.destination_airport_code) {
    renderDestAirports();
    show('step-destination-airports');
    return;
  }

  await doFlightSearch();
});

$('#btn-back-origin-airports').addEventListener('click', () => {
  state.origin_airport_code = null;
  show('step-input');
});

$('#btn-back-destination-airports').addEventListener('click', () => {
  state.destination_airport_code = null;
  if (needOriginAirport()) show('step-origin-airports');
  else {
    state.origin_airport_code = null;
    show('step-input');
  }
});

$('#btn-next-origin-airports').addEventListener('click', () => {
  if (!state.origin_airport_code) { alert('공항을 선택해 주세요.'); return; }
  if (needDestAirport() && !state.destination_airport_code) {
    renderDestAirports();
    show('step-destination-airports');
  } else {
    doFlightSearch();
  }
});

$('#btn-next-destination-airports').addEventListener('click', () => {
  if (!state.destination_airport_code) { alert('공항을 선택해 주세요.'); return; }
  doFlightSearch();
});

function fmtFlightDateTime(iso) {
  if (!iso) return '';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return iso;
  return `${m[2]}/${m[3]} ${m[4]}:${m[5]}`;
}

function renderFlights(flights, warnings) {
  const list = $('#flights-list');
  const warnEl = $('#flight-warnings');
  const mockEl = $('#flight-mock-notice');
  const sortBar = $('#flight-sort-bar');
  const stepTitle = $('#step-flights-title');
  const warns = warnings || [];

  if (stepTitle) {
    if (state.trip_type === 'multi_city') {
      const legNum = state.flightLeg.match(/multi_city_(\d+)/)?.[1];
      stepTitle.textContent = legNum != null ? `2-${parseInt(legNum) + 1}. 구간 ${parseInt(legNum) + 1} 항공편 선택` : '2. 항공편 선택';
    } else if (state.trip_type === 'round_trip') {
      stepTitle.textContent = '2. 왕복 항공편 선택';
    } else {
      stepTitle.textContent = state.flightLeg === 'return'
        ? '2b. 귀국 항공편 선택'
        : (state.trip_type === 'one_way' ? '2. 항공편 선택' : '2a. 출국 항공편 선택');
    }
  }
  const outboundSummary = $('#outbound-summary');
  const outboundSummaryText = $('#outbound-summary-text');
  if (outboundSummary && outboundSummaryText) {
    if (state.flightLeg === 'return' && state.selectedOutboundFlight) {
      const f = state.selectedOutboundFlight;
      const destL = f.destination_label ? `${f.destination || ''} (${f.destination_label})` : (f.destination || '');
      outboundSummaryText.textContent = `선택한 출국: ${f.airline} ${f.flight_number} ${f.origin} → ${destL}`;
      outboundSummary.classList.remove('hidden');
    } else if (state.trip_type === 'multi_city' && state.flightLeg !== 'multi_city_0' && state.selectedMultiCityFlights?.length > 0) {
      const prevLegs = state.selectedMultiCityFlights.filter(Boolean).map((f, i) => {
        const destL = f.destination_label ? `${f.destination || ''} (${f.destination_label})` : (f.destination || '');
        return `구간${i + 1}: ${f.airline} ${f.flight_number} ${f.origin}→${destL}`;
      });
      outboundSummaryText.textContent = '선택 완료: ' + prevLegs.join(' | ');
      outboundSummary.classList.remove('hidden');
    } else {
      outboundSummary.classList.add('hidden');
    }
  }
  if (flights) {
    state.currentFlights = flights;
  }
  const currentFlights = state.currentFlights || [];

  // 전체가 Mock인지 판별 (참고용 예시가 "추가"된 경우는 전체 Mock이 아님)
  const isMock = warns.some(w => w.includes('모두 실패하여 예시(Mock) 데이터를 반환')) ||
    (currentFlights.length > 0 && currentFlights.every(f => f?.source === 'mock'));

  if (mockEl) {
    if (isMock) {
      mockEl.textContent = '예시(Mock) 데이터입니다. 실제 예약·가격과 무관합니다.';
      mockEl.classList.remove('hidden');
    } else {
      mockEl.textContent = '';
      mockEl.classList.add('hidden');
    }
  }
  if (warnEl) {
    if (warns.length) {
      warnEl.innerHTML = warns.map(w => `<p class="api-warning">⚠️ ${w}</p>`).join('');
      warnEl.classList.remove('hidden');
    } else {
      warnEl.innerHTML = '';
      warnEl.classList.add('hidden');
    }
  }

  if (currentFlights.length > 0) {
    sortBar.classList.remove('hidden');
  } else {
    sortBar.classList.add('hidden');
  }

  list.innerHTML = currentFlights.map((f, i) => {
    const isRt = f.round_trip === true;
    const ob = isRt ? (f.outbound || f) : f;
    const ret = isRt ? (f.return || {}) : null;
    const destLabel = (ob.destination_label ? `${ob.destination || ''} (${ob.destination_label})` : ob.destination) || (f.destination_label ? `${f.destination || ''} (${f.destination_label})` : f.destination) || '';
    const route = isRt ? `${ob.origin || ''} ⇌ ${destLabel}` : `${f.origin || ''} → ${destLabel}`;
    const timeRange = isRt ? `${fmtFlightDateTime(ob.departure)} ~ ${fmtFlightDateTime(ret.arrival || ob.arrival)}` : `${fmtFlightDateTime(f.departure)} ~ ${fmtFlightDateTime(f.arrival)}`;
    const durOb = ob.duration_hours || 0;
    const durRet = ret.duration_hours || 0;
    const totalDur = isRt ? durOb + durRet : durOb;
    const duration = totalDur ? ` · 약 ${totalDur}시간` : '';
    const priceDisplay = (f.price_krw ? f.price_krw.toLocaleString() + '원' : (f.miles_required || 0) + '마일') + (isRt ? ' (왕복)' : '');
    const mileageBadge = f.mileage_eligible ? '<span class="flight-badge mileage">마일리지 적립</span>' : '';
    const mockBadge = (ob.source === 'mock_reference' || ob.source === 'mock' || f.source === 'mock')
      ? '<span class="flight-badge" style="background:#fff3cd; color:#856404; margin-left: 5px;">예시(Mock) 참고용</span>'
      : '';

    // Segments and layovers details
    let detailsHtml = '';
    const segsForDetails = isRt ? [...(ob.segments || []), ...(ret.segments || [])] : (f.segments || []);
    if (segsForDetails.length > 0) {
      detailsHtml += `<div class="flight-details hidden" id="flight-details-${i}" style="margin-top: 1rem; padding: 1rem; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.9em; background: rgba(0,0,0,0.15); border-radius: 0 0 8px 8px;">`;

      let isReturnFlightStarted = false;
      const outboundDateStart = ob.departure ? ob.departure.substring(0, 10) : "";
      const obSegCount = (ob.segments || []).length;

      segsForDetails.forEach((seg, sIdx) => {
        const dAirport = seg.departure_airport?.name || seg.departure_airport?.id || "";
        const aAirport = seg.arrival_airport?.name || seg.arrival_airport?.id || "";
        const dTimeStr = seg.departure_airport?.time?.substring(0, 19) || "";
        const dTime = fmtFlightDateTime(dTimeStr);
        const aTime = fmtFlightDateTime(seg.arrival_airport?.time?.substring(0, 19) || "");
        const segDur = seg.duration ? Math.round(seg.duration / 60) + '시간 ' + (seg.duration % 60) + '분' : '';

        // Detect if this segment is part of the return trip (if it is a round trip)
        const currentSegmentDate = dTimeStr.substring(0, 10);
        const showingRoundTripSegments = isRt || state.travelInput?.trip_type === 'round_trip';

        if (isRt && sIdx >= obSegCount && !isReturnFlightStarted) {
          isReturnFlightStarted = true;
          detailsHtml += `<hr style="border-color: rgba(255,255,255,0.2); margin: 1rem 0;">`;
          detailsHtml += `<div style="color: var(--accent); font-weight: bold; margin-bottom: 0.5rem;">[오는 편]</div>`;
        } else if (showingRoundTripSegments && !isRt && !isReturnFlightStarted && currentSegmentDate > outboundDateStart) {
          if (f.layovers && f.layovers[sIdx - 1] && f.layovers[sIdx - 1].duration > 1440) {
            isReturnFlightStarted = true;
            detailsHtml += `<hr style="border-color: rgba(255,255,255,0.2); margin: 1rem 0;">`;
            detailsHtml += `<div style="color: var(--accent); font-weight: bold; margin-bottom: 0.5rem;">[오는 편]</div>`;
          } else if (dAirport.includes(ob.destination) || (seg.departure_airport?.id || '') === (ob.destination || '')) {
            isReturnFlightStarted = true;
            detailsHtml += `<hr style="border-color: rgba(255,255,255,0.2); margin: 1rem 0;">`;
            detailsHtml += `<div style="color: var(--accent); font-weight: bold; margin-bottom: 0.5rem;">[오는 편]</div>`;
          }
        }

        if (sIdx === 0 && showingRoundTripSegments) {
          detailsHtml += `<div style="color: var(--accent); font-weight: bold; margin-bottom: 0.5rem;">[가는 편]</div>`;
        }

        detailsHtml += `
          <div style="margin-bottom: 0.5rem;">
            <strong>${seg.airline} ${seg.flight_number}</strong><br>
            <span style="color:var(--muted)">${dTime} ${dAirport} -> ${aTime} ${aAirport}</span>
            ${segDur ? `<br><span style="color:var(--accent); font-size:0.85em;">비행시간: ${segDur}</span>` : ''}
          </div>
        `;
        // Layover after this segment?
        if ((f.layovers || [])[sIdx]) {
          const lay = f.layovers[sIdx];
          // Ignore massive "layovers" that are actually just the destination stay for round trips
          if (lay.duration && lay.duration < 1440) {
            const layDur = lay.duration ? Math.round(lay.duration / 60) + '시간 ' + (lay.duration % 60) + '분' : '';
            detailsHtml += `<div style="padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 4px; margin-bottom: 0.5rem; text-align: center; color: var(--error);">
                 ⏳ 대기: ${lay.name || lay.id || '경유지'} (${layDur})
               </div>`;
          }
        }
      });
      detailsHtml += `
        <div style="margin-top: 1rem; text-align: right;">
          <button type="button" class="btn-select-flight text-sm" data-idx="${i}" style="padding: 0.4rem 1rem;">이 항공편 번호로 선택하기</button>
        </div>
      </div>`;
    } else {
      detailsHtml += `
        <div class="flight-details hidden" id="flight-details-${i}" style="margin-top: 1rem; padding: 1rem; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.9em; background: rgba(0,0,0,0.15); border-radius: 0 0 8px 8px;">
          <div style="margin-top: 0.5rem; text-align: right;">
            <button type="button" class="btn-select-flight text-sm" data-idx="${i}" style="padding: 0.4rem 1rem;">이 항공편 번호로 선택하기</button>
          </div>
        </div>`;
    }

    const routeDisplay = isRt ? route : (state.travelInput?.trip_type === 'round_trip' ? `${ob.origin || ''} ⇌ ${destLabel}` : route);

    return `
    <div class="option-item" data-idx="${i}" style="flex-direction: column; align-items: stretch; padding: 0;">
      <div class="flight-summary" style="padding: 1rem;">
        <h3>${ob.airline || '항공사'} ${ob.flight_number || ''} ${mileageBadge}${mockBadge}</h3>
        <p class="flight-route">${routeDisplay}</p>
        <p class="flight-time">${timeRange}${duration}</p>
        <p class="price">${priceDisplay}</p>
        <div style="text-align: right; margin-top: -1.5rem;">
          <span style="font-size:0.8em; color:var(--accent); text-decoration: underline;">상세 보기 ▼</span>
        </div>
      </div>
      ${detailsHtml}
    </div>
  `;
  }).join('');

  // Toggle Accordion Details
  list.querySelectorAll('.flight-summary').forEach(el => {
    el.addEventListener('click', (e) => {
      // Don't toggle if they clicked the select button obviously
      const item = el.closest('.option-item');
      const idx = item.dataset.idx;
      const details = document.getElementById(`flight-details-${idx}`);
      if (details.classList.contains('hidden')) {
        // Hide all others
        list.querySelectorAll('.flight-details').forEach(d => d.classList.add('hidden'));
        details.classList.remove('hidden');
      } else {
        details.classList.add('hidden');
      }
    });
  });

  // Select Flight Click
  list.querySelectorAll('.btn-select-flight').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = parseInt(btn.dataset.idx);
      selectFlight(state.currentFlights[idx]);
    });
  });
}

function selectFlight(f) {
  if (state.trip_type === 'multi_city') {
    const idx = parseInt((state.flightLeg.match(/multi_city_(\d+)/) || [,'0'])[1], 10);
    state.selectedMultiCityFlights = state.selectedMultiCityFlights || [];
    state.selectedMultiCityFlights[idx] = f;
  } else if (f.round_trip) {
    state.selectedOutboundFlight = { ...(f.outbound || {}), price_krw: f.price_krw, miles_required: f.miles_required };
    state.selectedReturnFlight = f.return || null;
  } else if (state.flightLeg === 'return') {
    state.selectedReturnFlight = f;
  } else {
    state.selectedOutboundFlight = f;
  }
  state.selectedFlight = buildSelectedFlight();
  const list = $('#flights-list');
  const sortBar = $('#flight-sort-bar');
  const summary = $('#selected-flight-summary');
  const summaryText = $('#selected-flight-text');
  const nextBtn = $('#btn-next-flights');

  list.classList.add('hidden');
  sortBar.classList.add('hidden');

  const disp = f.round_trip ? (f.outbound || f) : f;
  const destLabel = disp.destination_label ? `${disp.destination || ''} (${disp.destination_label})` : (disp.destination || '');
  const price = f.price_krw ? f.price_krw.toLocaleString() + '원 (왕복)' : (f.miles_required || 0) + '마일';
  const legLabel = state.trip_type === 'multi_city'
    ? `[구간${parseInt((state.flightLeg.match(/multi_city_(\d+)/) || [,'0'])[1], 10) + 1}] `
    : (f.round_trip ? '[왕복] ' : (state.flightLeg === 'return' ? '[귀국] ' : '[출국] '));
  summaryText.innerHTML = legLabel + `${disp.airline} ${disp.flight_number} - ${disp.origin} → ${destLabel} (${price})`;
  summary.classList.remove('hidden');

  nextBtn.disabled = false;
  nextBtn.style.opacity = '1';
  nextBtn.style.cursor = 'pointer';
  updateFlightNextButtonLabel();
}

function updateFlightNextButtonLabel() {
  const btn = $('#btn-next-flights');
  if (!btn) return;
  const tt = state.trip_type || $('#trip_type_select')?.value || 'round_trip';
  const isOutboundStep = state.flightLeg === 'outbound';
  const needsReturn = tt === 'round_trip' && !!state.selectedOutboundFlight && !state.selectedReturnFlight;
  if (isOutboundStep && needsReturn) {
    btn.textContent = '귀국편 검색';
    btn.title = '목적지→출발지 귀국편 검색';
  } else {
    btn.textContent = '다음';
    btn.title = '리스트에서 항공편을 선택해주세요';
  }
}

function buildSelectedFlight() {
  if (state.trip_type === 'multi_city') {
    const legs = (state.selectedMultiCityFlights || []).filter(Boolean);
    const mc = state.multi_cities || state.travelInput?.multi_cities || [];
    return legs.length > 0 ? { legs } : null;
  }
  if (state.trip_type === 'one_way' && state.selectedOutboundFlight) {
    return { outbound: state.selectedOutboundFlight };
  }
  if (state.trip_type === 'round_trip' && state.selectedOutboundFlight && state.selectedReturnFlight) {
    return { outbound: state.selectedOutboundFlight, return: state.selectedReturnFlight };
  }
  if (state.selectedOutboundFlight) {
    return { outbound: state.selectedOutboundFlight };
  }
  return null;
}

$('#btn-cancel-flight').addEventListener('click', () => {
  if (state.trip_type === 'multi_city') {
    const idx = parseInt((state.flightLeg.match(/multi_city_(\d+)/) || [,'0'])[1], 10);
    state.selectedMultiCityFlights = state.selectedMultiCityFlights || [];
    state.selectedMultiCityFlights[idx] = undefined;
  } else if (state.flightLeg === 'return') {
    state.selectedReturnFlight = null;
  } else {
    state.selectedOutboundFlight = null;
  }
  state.selectedFlight = buildSelectedFlight();
  $('#flights-list').classList.remove('hidden');
  $('#flight-sort-bar').classList.remove('hidden');
  $('#selected-flight-summary').classList.add('hidden');

  const nextBtn = $('#btn-next-flights');
  nextBtn.disabled = true;
  nextBtn.style.opacity = '0.5';
  nextBtn.style.cursor = 'not-allowed';
  updateFlightNextButtonLabel();
});

// Sorting Logic
$$('.sort-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    $$('.sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const sortType = btn.dataset.sort;
    if (!state.currentFlights || state.currentFlights.length === 0) return;

    let flights = [...state.currentFlights];

    const dur = (f) => {
      if (f.round_trip) return ((f.outbound || {}).duration_hours || 0) + ((f.return || {}).duration_hours || 0) || 999;
      return f.duration_hours || 999;
    };
    const price = (f) => f.price_krw ?? f.miles_required ?? 99999999;
    if (sortType === 'recommend') {
      flights.sort((a, b) => {
        const cat = (f) => {
          const ob = f.round_trip ? (f.outbound || f) : f;
          const pref = !!f.mileage_eligible;
          const direct = f.round_trip ? ((ob.is_direct !== false) && ((f.return || {}).is_direct !== false)) : (ob.is_direct !== false);
          if (pref && direct) return 0;
          if (pref && !direct) return 1;
          if (!pref && direct) return 2;
          return 3;
        };
        const ap = (f) => f.airport_priority ?? 99;
        const ca = cat(a), cb = cat(b);
        if (ca !== cb) return ca - cb;
        if (ap(a) !== ap(b)) return ap(a) - ap(b);
        if (dur(a) !== dur(b)) return dur(a) - dur(b);
        return price(a) - price(b);
      });
    } else if (sortType === 'price') {
      flights.sort((a, b) => price(a) - price(b));
    } else if (sortType === 'duration') {
      flights.sort((a, b) => dur(a) - dur(b));
    }

    // Sort된 데이터를 state에 다시 담고 다시 렌더 (경고도 빈 배열로 처리, 상단 배너 안 건드리게)
    state.currentFlights = flights;
    renderFlights();
  });
});

$('#btn-back-flights').addEventListener('click', () => {
  state.origin_airport_code = null;
  state.destination_airport_code = null;
  show('step-input');
});

$('#btn-next-flights').addEventListener('click', async () => {
  state.trip_type = $('#trip_type_select')?.value || state.travelInput?.trip_type || 'round_trip';
  const needsReturnSearch = state.trip_type === 'round_trip' && state.selectedOutboundFlight && !state.selectedReturnFlight;

  if (needsReturnSearch) {
    await doFlightSearch('return');
    return;
  }

  if (state.trip_type === 'multi_city') {
    const idx = parseInt((state.flightLeg.match(/multi_city_(\d+)/) || [,'0'])[1], 10);
    const selected = state.selectedMultiCityFlights?.[idx];
    if (!selected) {
      alert('항공편을 선택해 주세요.');
      return;
    }
    const mc = state.multi_cities || state.travelInput?.multi_cities || [];
    if (idx + 1 < mc.length) {
      state.flightLeg = `multi_city_${idx + 1}`;
      await doFlightSearch(state.flightLeg);
      return;
    }
  } else {
    if (state.flightLeg === 'outbound' && !state.selectedOutboundFlight) {
      alert('항공편을 선택해 주세요.');
      return;
    }
    if (state.flightLeg === 'return' && !state.selectedReturnFlight) {
      alert('항공편을 선택해 주세요.');
      return;
    }
  }

  state.selectedFlight = buildSelectedFlight();
  if (!state.selectedFlight) {
    alert('항공편 선택을 완료해 주세요.');
    return;
  }
  show('loading');
  try {
    const payload = { ...state.travelInput, selected_flight: state.selectedFlight };
    let data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);

    if (data?.step === 'rental') {
      state.localTransport = Array.isArray(data?.local_transport) ? data.local_transport : [];
      renderRentalOptions(state.localTransport);
      show('step-rental');
      return;
    }
    if (Array.isArray(data?.flights) && data.flights.length > 0 && !data?.step) {
      // Flight search results (fallback): incomplete selection triggered search
      const hasCompleteRoundTrip = state.trip_type === 'round_trip' && state.selectedOutboundFlight && state.selectedReturnFlight;
      if (hasCompleteRoundTrip) {
        // 출국+귀국 모두 선택됐는데 flights가 온 경우: rental 재요청 (백엔드가 잘못된 경로로 간 경우)
        const retryPayload = { ...state.travelInput, selected_flight: state.selectedFlight };
        const retryData = await callAgent(retryPayload);
        if (retryData?.step === 'rental') {
          state.localTransport = Array.isArray(retryData?.local_transport) ? retryData.local_transport : [];
          renderRentalOptions(state.localTransport);
          show('step-rental');
          return;
        }
        if (retryData?.error) throw new Error(retryData.error);
        throw new Error('다음 단계로 진행할 수 없습니다. 다시 시도해 주세요.');
      }
      state.flights = data.flights;
      state.flightWarnings = data?.warnings || [];
      if (state.trip_type === 'round_trip' && state.selectedOutboundFlight && !state.selectedReturnFlight) {
        state.flightLeg = 'return';
        state.selectedReturnFlight = null;
      }
      state.flightsByLeg[state.flightLeg] = data.flights;
      renderFlights(data.flights, state.flightWarnings);
      $('#flights-list').classList.remove('hidden');
      $('#flight-sort-bar').classList.remove('hidden');
      $('#selected-flight-summary').classList.add('hidden');
      if (state.flightLeg === 'return') state.selectedReturnFlight = null;
      show('step-flights');
      return;
    }
    if (data?.step === 'accommodation_and_transport') {
      state.accommodations = Array.isArray(data?.accommodations) ? data.accommodations : [];
      state.localTransport = Array.isArray(data?.local_transport) ? data.local_transport : [];
      renderAccommodations(state.accommodations);
      renderRentalOptions(state.localTransport);
      show('step-accommodation');
      return;
    }

    let itin = Array.isArray(data) ? data : (data?.itineraries || data);
    if (!Array.isArray(itin)) itin = [itin];
    state.itineraries = itin;
    renderItineraries(state.itineraries);
    show('step-itineraries');
  } catch (err) {
    showError(err.message);
  }
});

function renderRentalOptions(items) {
  const list = $('#rental-list');
  if (!list) return;
  const isRental = state.travelInput?.local_transport === 'rental_car';
  list.innerHTML = (items || []).map((opt, i) => {
    if (isRental && (opt.image_url || opt.vehicle_name || opt.booking_url)) {
      const seatsLabel = opt.seats ? ` (${opt.seats}인승)` : '';
      const title = opt.provider ? `${opt.provider} - ${opt.car_type || ''}${seatsLabel}` : (opt.car_type || `옵션 ${i + 1}`) + seatsLabel;
      const features = Array.isArray(opt.features) ? opt.features.join(' · ') : opt.features || '';
      const imgHtml = opt.image_url ? `<img src="${opt.image_url}" alt="${opt.vehicle_name || opt.car_type}" class="rental-card-img" loading="lazy">` : '';
      const detailHtml = opt.description || opt.vehicle_name ? `<p class="rental-desc">${opt.vehicle_name || ''}${opt.description ? ' · ' + opt.description : ''}</p>` : '';
      const luggageHtml = opt.luggage_capacity ? `<span class="rental-luggage">수하물: ${opt.luggage_capacity}</span>` : '';
      const bookingBtn = opt.booking_url ? `<a href="${opt.booking_url}" target="_blank" rel="noopener" class="btn-booking" onclick="event.stopPropagation()">예약 사이트 연결</a>` : '';
      return `
        <div class="option-item rental-card" data-idx="${i}">
          <div class="rental-card-media">${imgHtml}</div>
          <div class="rental-card-body">
            <h3>${title}</h3>
            ${detailHtml}
            ${features ? `<p class="rental-features">${features}</p>` : ''}
            ${luggageHtml}
            <p class="rental-location">${[opt.pickup_location, opt.dropoff_location].filter(Boolean).join(' → ')}</p>
            <div class="rental-footer">
              <span class="price">${opt.price_total_krw ? opt.price_total_krw.toLocaleString() + '원' : ''}</span>
              ${bookingBtn}
            </div>
          </div>
        </div>
      `;
    }
    let title = '', desc = '';
    if (isRental) {
      const seatsLabel = opt.seats ? ` (${opt.seats}인승)` : '';
      title = opt.provider ? `${opt.provider} - ${opt.car_type || ''}${seatsLabel}` : (opt.car_type || `옵션 ${i + 1}`) + seatsLabel;
      desc = [opt.pickup_location, opt.dropoff_location].filter(Boolean).join(' → ');
      if (opt.price_total_krw) desc += ` | ${opt.price_total_krw.toLocaleString()}원`;
    } else {
      title = opt.description || opt.route_id || `옵션 ${i + 1}`;
      desc = opt.duration_minutes ? `약 ${opt.duration_minutes}분` : '';
      if (opt.pass_price_krw) desc += ` | ${opt.pass_price_krw.toLocaleString()}원`;
    }
    return `
      <div class="option-item" data-idx="${i}">
        <h3>${title}</h3>
        <p>${desc}</p>
      </div>
    `;
  }).join('');
  list.querySelectorAll('.option-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target?.closest('.btn-booking')) return;
      list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.selectedLocalTransport = items[parseInt(el.dataset.idx)];
      updateRentalBookingButton();
    });
  });
  if (items && items.length > 0 && !state.selectedLocalTransport) {
    state.selectedLocalTransport = items[0];
    list.querySelector('.option-item')?.classList.add('selected');
  }
  updateRentalBookingButton();
}

function updateRentalBookingButton() {
  const btn = $('#btn-booking-rental');
  if (!btn) return;
  const sel = state.selectedLocalTransport;
  if (sel?.booking_url) {
    btn.href = sel.booking_url;
    btn.style.display = 'inline-flex';
  } else {
    btn.style.display = 'none';
  }
}

function renderItineraries(items) {
  const list = $('#itineraries-list');
  list.innerHTML = items.map((it, i) => `
    <div class="option-item" data-idx="${i}">
      <h3>${it.title || `일정 ${i + 1}`}</h3>
      <p>${it.summary || ''}</p>
    </div>
  `).join('');
  list.querySelectorAll('.option-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.selectedItinerary = items[parseInt(el.dataset.idx)];
    });
  });
}

$('#btn-back-rental').addEventListener('click', () => show('step-flights'));
$('#btn-next-rental').addEventListener('click', async () => {
  state.selectedLocalTransport = state.selectedLocalTransport || (state.localTransport && state.localTransport[0]) || {};
  show('loading');
  try {
    const payload = {
      ...state.travelInput,
      selected_flight: buildSelectedFlight(),
      selected_local_transport: state.selectedLocalTransport,
    };
    const data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    let itin = Array.isArray(data) ? data : (data?.itineraries || data);
    if (!Array.isArray(itin)) itin = [itin];
    state.itineraries = itin;
    renderItineraries(state.itineraries);
    show('step-itineraries');
  } catch (err) {
    showError(err.message);
  }
});

$('#btn-back-itineraries').addEventListener('click', () => show('step-rental'));

$('#btn-next-itineraries').addEventListener('click', async () => {
  if (!state.selectedItinerary) { alert('일정을 선택해 주세요.'); return; }
  show('loading');
  try {
    const payload = {
      ...state.travelInput,
      selected_flight: state.selectedFlight,
      selected_itinerary: state.selectedItinerary,
    };
    const data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    const acc = data?.accommodations || [];
    const lt = data?.local_transport || [];
    state.accommodations = Array.isArray(acc) ? acc : [];
    state.localTransport = Array.isArray(lt) ? lt : [];
    renderAccommodations(state.accommodations);
    $('#local-transport-info').innerHTML = state.localTransport.length
      ? `<h4>현지 이동</h4><pre>${JSON.stringify(state.localTransport, null, 2)}</pre>`
      : '';
    show('step-accommodation');
  } catch (err) {
    showError(err.message);
  }
});

function renderAccommodations(items) {
  const list = $('#accommodations-list');
  list.innerHTML = items.map((a, i) => `
    <div class="option-item" data-idx="${i}">
      <h3>${a.name || ''}</h3>
      <p>${a.location || ''} | ${a.price_per_night_krw ? a.price_per_night_krw.toLocaleString() + '원/박' : ''}</p>
    </div>
  `).join('');
  list.querySelectorAll('.option-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.selectedAccommodation = items[parseInt(el.dataset.idx)];
    });
  });
}

$('#btn-back-accommodation').addEventListener('click', () => show('step-itineraries'));

$('#btn-confirm-booking').addEventListener('click', async () => {
  if (!state.selectedAccommodation) { alert('숙소를 선택해 주세요.'); return; }
  show('loading');
  try {
    const payload = {
      ...state.travelInput,
      selected_flight: state.selectedFlight,
      selected_itinerary: state.selectedItinerary,
      selected_accommodation: state.selectedAccommodation,
    };
    const data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    $('#booking-guidance').innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    show('step-confirm');
  } catch (err) {
    showError(err.message);
  }
});

/* --- 달력 선택 --- */
let calendarTarget = null;
let calendarDate = new Date();

function renderCalendar() {
  const year = calendarDate.getFullYear();
  const month = calendarDate.getMonth();
  const first = new Date(year, month, 1);
  const last = new Date(year, month + 1, 0);
  const startDay = first.getDay();
  const daysInMonth = last.getDate();

  $('#calendar-month').textContent = `${year}년 ${month + 1}월`;

  const startInput = $('#start_date_input')?.value;
  const endInput = $('#end_date_input')?.value;
  let selectedStart = null;
  let selectedEnd = null;

  if (calendarTarget && calendarTarget.startsWith('multi_')) {
    const idx = parseInt(calendarTarget.split('_')[1], 10);
    const val = state.multi_cities[idx]?.date;
    selectedStart = val ? new Date(val + 'T12:00:00') : null;
  } else {
    selectedStart = startInput ? new Date(startInput + 'T12:00:00') : null;
    selectedEnd = endInput ? new Date(endInput + 'T12:00:00') : null;
  }

  let html = '';
  for (let i = 0; i < startDay; i++) {
    const d = new Date(year, month, -startDay + i + 1);
    const ymd = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    html += `<span class="other-month" data-date="${ymd}">${d.getDate()}</span>`;
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, month, d);
    const ymd = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    let cls = '';
    if (selectedStart && date.getTime() === selectedStart.getTime()) cls = 'selected';
    if (selectedEnd && date.getTime() === selectedEnd.getTime()) cls = 'selected';
    html += `<span data-date="${ymd}" ${cls ? `class="${cls}"` : ''}>${d}</span>`;
  }
  const totalCells = startDay + daysInMonth;
  const remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
  for (let i = 0; i < remaining; i++) {
    const nextDate = new Date(year, month + 1, i + 1);
    const ymd = `${nextDate.getFullYear()}-${String(nextDate.getMonth() + 1).padStart(2, '0')}-${String(nextDate.getDate()).padStart(2, '0')}`;
    html += `<span class="other-month" data-date="${ymd}">${nextDate.getDate()}</span>`;
  }

  $('#calendar-days').innerHTML = html;
  const startVal = $('#start_date_input')?.value;
  const endVal = $('#end_date_input')?.value;

  $('#calendar-days').querySelectorAll('span[data-date]').forEach(span => {
    const ymd = span.dataset.date;
    if (!ymd) return;
    if (calendarTarget === 'end' && startVal) {
      if (ymd < startVal) span.classList.add('disabled');
    }
    span.addEventListener('click', () => {
      if (span.classList.contains('disabled')) return;
      if (calendarTarget && calendarTarget.startsWith('multi_')) {
        const idx = parseInt(calendarTarget.split('_')[1], 10);
        state.multi_cities[idx].date = ymd;
        renderMultiCityLegs();
      } else if (calendarTarget === 'start') {
        $('#start_date_input').value = ymd;
        if (endVal && ymd > endVal) $('#end_date_input').value = '';
      } else if (calendarTarget === 'end') {
        if (startVal && ymd < startVal) return;
        $('#end_date_input').value = ymd;
      }
      calendarTarget = null;
      $('#calendar-picker').classList.add('hidden');
      saveFormToStorage();
      renderCalendar();
    });
  });
}

function openCalendar(target) {
  calendarTarget = target;
  let val = '';
  if (target.startsWith('multi_')) {
    const idx = parseInt(target.split('_')[1], 10);
    val = state.multi_cities[idx]?.date;
  } else {
    const input = target === 'start' ? $('#start_date_input') : $('#end_date_input');
    val = input?.value;
    if (target === 'end' && !val) {
      const startVal = $('#start_date_input')?.value;
      if (startVal) val = startVal;
    }
  }
  if (val) {
    const [y, m] = val.split('-').map(Number);
    calendarDate = new Date(y, m - 1, 1);
  } else {
    calendarDate = new Date();
  }
  renderCalendar();
  $('#calendar-picker').classList.remove('hidden');
}

function initStepIndicator() {
  show('step-input');
  loadFormFromStorage();
  initTripTypeUI();
  renderPlanUI();
  initPlanToolbar();

  $$('#step-indicator .step-node').forEach(node => {
    node.style.cursor = 'pointer';
    node.setAttribute('title', '클릭하여 해당 단계로 이동');
    node.addEventListener('click', () => {
      const step = node.dataset.step;
      if (step) navigateToStep(step);
    });
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initStepIndicator);
} else {
  initStepIndicator();
}

function initTripTypeUI() {
  const select = $('#trip_type_select');
  if (!select) return;
  const val = select.value;
  const single = $('#single-trip-fields');
  const multi = $('#multi-city-fields');
  const endDateLabel = $('#end-date-label');

  if (val === 'multi_city') {
    single.classList.add('hidden');
    multi.classList.remove('hidden');
    if (state.multi_cities.length === 0) {
      state.multi_cities = [
        { origin: '', destination: '', date: '' },
        { origin: '', destination: '', date: '' }
      ];
    }
    renderMultiCityLegs();
  } else {
    single.classList.remove('hidden');
    multi.classList.add('hidden');
    if (val === 'one_way') {
      endDateLabel.style.visibility = 'hidden';
      $('#end_date_input').required = false;
    } else {
      endDateLabel.style.visibility = 'visible';
      $('#end_date_input').required = true;
    }
  }
}

$('#trip_type_select')?.addEventListener('change', () => {
  initTripTypeUI();
  saveFormToStorage();
});

function renderMultiCityLegs() {
  const container = $('#multi-city-legs');
  if (!container) return;

  container.innerHTML = state.multi_cities.map((leg, i) => `
    <div class="form-row multi-city-leg" data-idx="${i}" style="align-items: center; background: #fafafa; padding: 10px; border-radius: 4px;">
      <span style="font-weight: bold; margin-right: 10px;">${i + 1}</span>
      <label>출발 <input type="text" class="mc-origin" value="${leg.origin}" placeholder="예: ICN" required></label>
      <label>도착 <input type="text" class="mc-dest" value="${leg.destination}" placeholder="예: NRT" required></label>
      <label>날짜 
        <div class="date-row">
          <input type="text" class="mc-date" value="${leg.date}" placeholder="YYYY-MM-DD" required readonly>
          <button type="button" class="calendar-btn mc-cal" data-idx="${i}" title="달력">📅</button>
        </div>
      </label>
      ${state.multi_cities.length > 2 ? `<button type="button" class="secondary mc-remove" data-idx="${i}" style="margin-left: 10px;">삭제</button>` : ''}
    </div>
  `).join('');

  $$('.mc-remove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const idx = parseInt(e.target.dataset.idx);
      updateStateFromMultiCityDOM();
      state.multi_cities.splice(idx, 1);
      renderMultiCityLegs();
      saveFormToStorage();
    });
  });

  $$('.mc-cal').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const idx = parseInt(e.currentTarget.dataset.idx);
      openCalendar('multi_' + idx);
    });
  });

  $$('.multi-city-leg input').forEach(input => {
    input.addEventListener('change', () => {
      updateStateFromMultiCityDOM();
      saveFormToStorage();
    });
  });
}

function updateStateFromMultiCityDOM() {
  const legs = $$('.multi-city-leg');
  if (!legs.length) return;
  state.multi_cities = Array.from(legs).map(leg => ({
    origin: leg.querySelector('.mc-origin').value,
    destination: leg.querySelector('.mc-dest').value,
    date: leg.querySelector('.mc-date').value
  }));
}

$('#btn-add-leg')?.addEventListener('click', () => {
  updateStateFromMultiCityDOM();
  if (state.multi_cities.length >= 20) {
    alert('다구간은 최대 20개까지만 추가할 수 있습니다.');
    return;
  }

  const last = state.multi_cities[state.multi_cities.length - 1];
  state.multi_cities.push({
    origin: last ? last.destination : '',
    destination: '',
    date: ''
  });
  renderMultiCityLegs();
  saveFormToStorage();
});

$('#travel-form')?.addEventListener('input', saveFormToStorage);
$('#travel-form')?.addEventListener('change', saveFormToStorage);

function initPlanToolbar() {
  const btnNew = $('#btn-new-plan');
  const btnSave = $('#btn-save-plan');
  const btnSaveAs = $('#btn-save-as-plan');
  const btnOpen = $('#btn-open-plan');
  if (btnNew) btnNew.addEventListener('click', onNewPlanClick);
  if (btnSave) btnSave.addEventListener('click', onSavePlanClick);
  if (btnSaveAs) btnSaveAs.addEventListener('click', onSaveAsPlanClick);
  if (btnOpen) btnOpen.addEventListener('click', onOpenPlanClick);
  $('#btn-close-plan-modal')?.addEventListener('click', closePlanModal);
  $('#plan-open-modal .modal-backdrop')?.addEventListener('click', closePlanModal);
  $('#btn-copy-code')?.addEventListener('click', () => {
    const uid = getUserId();
    if (uid && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(uid);
      alert('연결 코드가 복사되었습니다.');
    }
  });
  $('#btn-link-device')?.addEventListener('click', async () => {
    const input = $('#user-code-input');
    const code = input?.value?.trim();
    if (!code || code.length < 4) {
      alert('연결 코드를 입력하세요 (4자 이상).');
      return;
    }
    setUserId(code);
    updateUserCodeDisplay();
    if (input) input.value = '';
    await renderPlanListInModal();
  });
}
function onNewPlanClick() {
  if (state.currentPlanId || state.travelInput || state.flights?.length || state.itineraries?.length) {
    if (!confirm('현재 진행 중인 내용이 저장되지 않을 수 있습니다. 새 계획을 만드시겠습니까?')) return;
  }
  newPlan();
}
async function onSavePlanClick() {
  const ok = await savePlan();
  if (ok) {
    alert('저장되었습니다.');
    renderPlanUI();
  } else {
    alert('저장할 내용이 없거나 이름 입력이 취소되었습니다.');
  }
}
async function onSaveAsPlanClick() {
  const ok = await savePlan(null, true);
  if (ok) {
    alert('다른 이름으로 저장되었습니다.');
    renderPlanUI();
  } else {
    alert('저장할 내용이 없거나 이름 입력이 취소되었습니다.');
  }
}
async function onOpenPlanClick() {
  $('#plan-open-modal').classList.remove('hidden');
  $('#plan-open-modal').setAttribute('aria-hidden', 'false');
  updateUserCodeDisplay();
  await renderPlanListInModal();
}
function updateUserCodeDisplay() {
  const el = $('#user-code-display');
  if (el) el.textContent = getUserId() || '-';
}
async function renderPlanListInModal() {
  const list = $('#plan-list');
  if (!list) return;
  list.innerHTML = '<p class="muted">불러오는 중...</p>';
  await ensureUserId();
  const plans = await getSavedPlansFromServer();
  if (plans.length === 0) {
    list.innerHTML = '<p class="muted">저장된 계획이 없습니다.</p>';
  } else {
    list.innerHTML = plans.map(p => `
      <div class="plan-list-item" data-id="${p.id}">
        <div class="plan-item-main">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="plan-item-meta">${formatPlanDate(p.updatedAt)}</span>
        </div>
        <div class="plan-item-actions">
          <button type="button" class="plan-btn-open" data-id="${p.id}">열기</button>
          <button type="button" class="plan-btn-delete secondary" data-id="${p.id}" title="삭제">삭제</button>
        </div>
      </div>
    `).join('');
    list.querySelectorAll('.plan-btn-open').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        await openPlan(e.target.dataset.id);
        closePlanModal();
      });
    });
    list.querySelectorAll('.plan-btn-delete').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (confirm('이 계획을 삭제하시겠습니까?')) {
          await deletePlan(e.target.dataset.id);
          await renderPlanListInModal();
        }
      });
    });
  }
}

function closePlanModal() {
  $('#plan-open-modal')?.classList.add('hidden');
  $('#plan-open-modal')?.setAttribute('aria-hidden', 'true');
}
function escapeHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
function formatPlanDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch (_) { return iso; }
}

$('#btn-calendar-start').addEventListener('click', () => openCalendar('start'));
$('#btn-calendar-end').addEventListener('click', () => openCalendar('end'));

$('#calendar-prev').addEventListener('click', () => {
  calendarDate.setMonth(calendarDate.getMonth() - 1);
  renderCalendar();
});

$('#calendar-next').addEventListener('click', () => {
  calendarDate.setMonth(calendarDate.getMonth() + 1);
  renderCalendar();
});
