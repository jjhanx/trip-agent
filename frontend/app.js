/* Trip Agent - Web UI */

/** YYYY-MM-DD(또는 그 앞 10자)를 로컬 달력 날짜로 해석해 포함 일수를 맞춘다(UTC 파싱 시 발생 가능한 ±1일 오차 방지). */
function inclusiveCalendarDays(startStr, endStr) {
  if (!startStr || !endStr) return 1;
  const parse = (s) => {
    const p = String(s).slice(0, 10).split('-').map(Number);
    if (p.length !== 3 || p.some((x) => Number.isNaN(x))) return null;
    return new Date(p[0], p[1] - 1, p[2]);
  };
  const a = parse(startStr);
  const b = parse(endStr);
  if (!a || !b) return 1;
  const diff = Math.round((b - a) / 86400000);
  return Math.max(1, diff + 1);
}

/** 폼(출발·귀환일 등)과 동기화된 travelInput. 세션/일정 API 호출 직전에 반드시 호출해 stale 날짜 전송을 막는다. */
function syncTravelInputFromForm() {
  state.travelInput = buildTravelInput();
  state.trip_type = state.travelInput?.trip_type || $('#trip_type_select')?.value || 'round_trip';
  state.multi_cities = state.travelInput?.multi_cities || state.multi_cities || [];
  return state.travelInput;
}

/** 세션 A2A 요청 공통: 여행 입력 + 항공/렌트 건너뛰기 플래그 */
function baseSessionPayload(extra = {}) {
  syncTravelInputFromForm();
  return {
    ...state.travelInput,
    flight_skipped: !!state.flightSkipped,
    rental_skipped: !!state.rentalSkipped,
    ...extra,
  };
}

/** 선택 항공과 동일한 기준으로 여행 시작·종료일(YYYY-MM-DD). 세션 `_extract_rental_dates_from_flight`와 맞춤. */
function tripDatesFromSelectedFlight() {
  const sf = buildSelectedFlight();
  if (!sf) return null;
  const dateOnly = (s) => (s && typeof s === 'string' && s.length >= 10) ? s.slice(0, 10) : null;
  const tt = state.trip_type || $('#trip_type_select')?.value || 'round_trip';
  if (tt === 'multi_city' && Array.isArray(sf.legs) && sf.legs.length > 0) {
    const first = sf.legs[0];
    const last = sf.legs[sf.legs.length - 1];
    return {
      start: dateOnly(first.arrival || first.departure),
      end: dateOnly(last.departure || last.arrival),
    };
  }
  const ob = sf.outbound;
  if (!ob) return null;
  const start = dateOnly(ob.arrival);
  let end = null;
  if (tt === 'round_trip' && sf.return) {
    end = dateOnly(sf.return.departure);
  }
  return { start, end };
}

/** 항공 확정 후 폼의 출발·귀환일을 실제 편 일정에 맞춤(초기 폼 6/25 vs 편 6/23 등). */
function applyFlightDatesToTravelForm() {
  const d = tripDatesFromSelectedFlight();
  if (!d) return;
  const fs = $('#travel-form');
  if (!fs) return;
  if (d.start && fs.start_date) fs.start_date.value = d.start;
  if (d.end && fs.end_date) fs.end_date.value = d.end;
  try {
    saveFormToStorage();
  } catch (_) { /* ignore */ }
}

const API_BASE = window.location.origin + '/a2a/';
const API_PLANS = window.location.origin + '/api';
const STORAGE_KEY = 'trip-agent-form';
const PLANS_STORAGE_KEY = 'trip-agent-plans';
const ITINERARY_DRAFT_KEY = 'trip-agent-itinerary-draft';
const USER_ID_KEY = 'trip-agent-user-id';

/** 동일 여행인지 판별해, 목적지·기간·공항 등이 바뀌면 일정 초안을 쓰지 않는다. */
function itineraryDraftFingerprint() {
  syncTravelInputFromForm();
  const ti = state.travelInput;
  const parts = [
    ti?.origin || '',
    ti?.destination || '',
    String(ti?.start_date || ''),
    String(ti?.end_date || ''),
    ti?.trip_type || '',
    state.flightSkipped ? '1' : '0',
    state.rentalSkipped ? '1' : '0',
    state.destination_airport_code || '',
    state.origin_airport_code || '',
  ];
  return parts.join('|');
}

function saveItineraryDraft() {
  try {
    const fp = itineraryDraftFingerprint();
    const draft = {
      fp,
      itineraryWorkflowStep: state.itineraryWorkflowStep,
      itineraryAttractionCatalog: state.itineraryAttractionCatalog,
      itineraryTripDays: state.itineraryTripDays,
      itineraryRouteBundle: state.itineraryRouteBundle,
      selectedAttractionIds: state.selectedAttractionIds,
      mealChoices: state.mealChoices,
      selectedItinerary: state.selectedItinerary,
      itineraries: state.itineraries,
    };
    localStorage.setItem(ITINERARY_DRAFT_KEY, JSON.stringify(draft));
  } catch (e) {
    console.warn('saveItineraryDraft failed', e);
  }
}

function clearItineraryDraft() {
  try {
    localStorage.removeItem(ITINERARY_DRAFT_KEY);
  } catch (_) { /* ignore */ }
}

function restoreItineraryDraft() {
  try {
    const raw = localStorage.getItem(ITINERARY_DRAFT_KEY);
    if (!raw) return;
    const draft = JSON.parse(raw);
    syncTravelInputFromForm();
    const fp = itineraryDraftFingerprint();
    if (!draft.fp || draft.fp !== fp) {
      clearItineraryDraft();
      return;
    }
    if (draft.itineraryWorkflowStep != null) state.itineraryWorkflowStep = draft.itineraryWorkflowStep;
    state.itineraryAttractionCatalog = Array.isArray(draft.itineraryAttractionCatalog)
      ? draft.itineraryAttractionCatalog
      : [];
    sanitizeAttractionCatalogInPlace(state.itineraryAttractionCatalog);
    state.itineraryTripDays = draft.itineraryTripDays != null ? draft.itineraryTripDays : null;
    state.itineraryRouteBundle = draft.itineraryRouteBundle && typeof draft.itineraryRouteBundle === 'object'
      ? draft.itineraryRouteBundle
      : null;
    state.selectedAttractionIds = Array.isArray(draft.selectedAttractionIds) ? draft.selectedAttractionIds : [];
    state.mealChoices = draft.mealChoices && typeof draft.mealChoices === 'object' ? draft.mealChoices : {};
    state.selectedItinerary = draft.selectedItinerary ?? null;
    state.itineraries = Array.isArray(draft.itineraries) ? draft.itineraries : [];
    if (state.selectedItinerary && !state.itineraryWorkflowStep) {
      const si = state.selectedItinerary;
      if (si && typeof si === 'object' && !si.option_id && (si.daily_plan || si.summary || si.title)) {
        state.itineraryWorkflowStep = 'complete';
      }
    }
  } catch (e) {
    console.warn('restoreItineraryDraft failed', e);
  }
}

function normalizeAttractionKey(name) {
  if (!name) return '';
  return String(name)
    .toLowerCase()
    .replace(/\([^)]*\)/g, '')
    .replace(/（[^）]*）/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 서버가 새 id로 카탈로그를 다시 줄 때 place_id·이름으로 선택을 이어 붙인다. */
function reconcileAttractionIdsAfterCatalogUpdate(prevCatalog, selectedIds, newCatalog) {
  if (!Array.isArray(newCatalog) || newCatalog.length === 0) return [];
  const prevList = Array.isArray(prevCatalog) ? prevCatalog : [];
  const refs = (selectedIds || []).map((id) => {
    const a = prevList.find((x) => x && x.id === id);
    return a
      ? { place_id: (a.place_id && String(a.place_id).trim()) || '', name: (a.name && String(a.name)) || '' }
      : { place_id: '', name: '' };
  });
  const out = [];
  const seen = new Set();
  for (const ref of refs) {
    let hit = null;
    if (ref.place_id) {
      hit = newCatalog.find((x) => x && x.place_id && String(x.place_id).trim() === ref.place_id);
    }
    if (!hit && ref.name) {
      const k = normalizeAttractionKey(ref.name);
      hit = newCatalog.find((x) => x && normalizeAttractionKey(x.name || '') === k);
    }
    if (hit && hit.id && !seen.has(hit.id)) {
      out.push(hit.id);
      seen.add(hit.id);
    }
  }
  return out;
}

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
    flightSearchApi: state.flightSearchApi || '',
    flightSkipped: !!state.flightSkipped,
    rentalSkipped: !!state.rentalSkipped,
    travelPrimaryIntent: state.travelPrimaryIntent,
    rentalDecideFrom: state.rentalDecideFrom,
    selectedOutboundFlight: state.selectedOutboundFlight,
    selectedReturnFlight: state.selectedReturnFlight,
    selectedMultiCityFlights: state.selectedMultiCityFlights,
    selectedFlight: state.selectedFlight,
    flightLeg: state.flightLeg,
    itineraries: state.itineraries,
    selectedItinerary: state.selectedItinerary,
    itineraryWorkflowStep: state.itineraryWorkflowStep,
    itineraryAttractionCatalog: state.itineraryAttractionCatalog,
    itineraryTripDays: state.itineraryTripDays,
    itineraryRouteBundle: state.itineraryRouteBundle,
    selectedAttractionIds: state.selectedAttractionIds,
    mealChoices: state.mealChoices,
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
  state.flightSearchApi = typeof data.flightSearchApi === 'string' ? data.flightSearchApi : '';
  state.flightSkipped = !!data.flightSkipped;
  state.rentalSkipped = !!data.rentalSkipped;
  state.travelPrimaryIntent = data.travelPrimaryIntent ?? null;
  state.rentalDecideFrom = data.rentalDecideFrom ?? null;
  state.selectedOutboundFlight = data.selectedOutboundFlight ?? null;
  state.selectedReturnFlight = data.selectedReturnFlight ?? null;
  state.selectedMultiCityFlights = Array.isArray(data.selectedMultiCityFlights) ? data.selectedMultiCityFlights : [];
  state.selectedFlight = data.selectedFlight ?? null;
  state.flightLeg = data.flightLeg ?? 'outbound';
  state.itineraries = Array.isArray(data.itineraries) ? data.itineraries : [];
  state.selectedItinerary = data.selectedItinerary ?? null;
  state.itineraryWorkflowStep = data.itineraryWorkflowStep ?? null;
  state.itineraryAttractionCatalog = Array.isArray(data.itineraryAttractionCatalog) ? data.itineraryAttractionCatalog : [];
  sanitizeAttractionCatalogInPlace(state.itineraryAttractionCatalog);
  state.itineraryTripDays = data.itineraryTripDays != null ? data.itineraryTripDays : null;
  state.itineraryRouteBundle = data.itineraryRouteBundle && typeof data.itineraryRouteBundle === 'object' ? data.itineraryRouteBundle : null;
  state.selectedAttractionIds = Array.isArray(data.selectedAttractionIds) ? data.selectedAttractionIds : [];
  state.mealChoices = data.mealChoices && typeof data.mealChoices === 'object' ? data.mealChoices : {};
  if (state.selectedItinerary && !state.itineraryWorkflowStep) {
    const si = state.selectedItinerary;
    if (si && typeof si === 'object' && !si.option_id && (si.daily_plan || si.summary || si.title)) {
      state.itineraryWorkflowStep = 'complete';
    }
  }
  state.accommodations = Array.isArray(data.accommodations) ? data.accommodations : [];
  state.selectedAccommodation = data.selectedAccommodation ?? null;
  state.localTransport = normalizeLocalTransport(data.localTransport);
  state.selectedLocalTransport = data.selectedLocalTransport ?? null;
  validateDestinationAirportMatchesDestination();
  applyDefaultDestinationAirportIfMissing();
  try {
    saveFormToStorage();
  } catch (_) { /* ignore */ }
  saveItineraryDraft();
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
  if (state.selectedAccommodation) return 'booking';
  if (state.accommodations?.length) return 'accommodation';
  if (state.selectedItinerary && !state.accommodations?.length) return 'itinerary';
  const ws = state.itineraryWorkflowStep;
  if (ws === 'attractions') return 'attractions';
  if (ws === 'meals' || ws === 'complete' || ws === 'legacy') return 'itinerary';
  if (state.itineraries?.length) return 'itinerary';
  if (state.itineraryRouteBundle || state.selectedItinerary) return 'itinerary';
  if (state.itineraryAttractionCatalog?.length) return 'attractions';
  if (state.selectedLocalTransport || state.localTransport?.length) return 'rental';
  if (state.flightSkipped && !buildSelectedFlight()) return 'rental';
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
  state.itineraryWorkflowStep = null;
  state.itineraryAttractionCatalog = [];
  state.itineraryTripDays = null;
  state.itineraryRouteBundle = null;
  state.selectedAttractionIds = [];
  state.mealChoices = {};
  state.accommodations = [];
  state.selectedAccommodation = null;
  state.localTransport = [];
  state.selectedLocalTransport = null;
  state.flightWarnings = [];
  state.flightSearchApi = '';
  state.flightSkipped = false;
  state.rentalSkipped = false;
  state.travelPrimaryIntent = null;
  state.rentalDecideFrom = null;
  clearItineraryDraft();
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
  flightSearchApi: '',
  flightLeg: 'outbound',
  flightSkipped: false,
  rentalSkipped: false,
  travelPrimaryIntent: null,
  rentalDecideFrom: null,
  itineraries: [],
  selectedItinerary: null,
  itineraryWorkflowStep: null,
  itineraryAttractionCatalog: [],
  itineraryTripDays: null,
  itineraryRouteBundle: null,
  selectedAttractionIds: [],
  mealChoices: {},
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
  'step-rental-decide': 'rental',
  'step-rental': 'rental',
  'step-itinerary-decide': 'attractions',
  'step-attractions': 'attractions',
  'step-itinerary-plan': 'itinerary',
  'step-accommodation-decide': 'accommodation',
  'step-accommodation': 'accommodation',
  'step-confirm': 'booking',
};

const STEP_TO_SECTION = {
  input: 'step-input',
  flights: 'step-flights',
  rental: 'step-rental',
  attractions: 'step-attractions',
  itinerary: 'step-itinerary-plan',
  accommodation: 'step-accommodation',
  confirm: 'step-confirm',
  booking: 'step-confirm',
};

function mountItineraryStepPanel(which) {
  const panel = $('#itinerary-step-panel');
  const targetId = which === 'plan' ? 'itinerary-step-panel-mount-plan' : 'itinerary-step-panel-mount-attractions';
  const target = $(`#${targetId}`);
  if (panel && target && panel.parentElement !== target) {
    target.appendChild(panel);
  }
}

/** 저장·복원된 확정 일정(요약·일자별). 일정 옵션 카드·건너뛰기 스텁은 제외. */
function selectedItineraryLooksFinal(si) {
  if (!si || typeof si !== 'object') return false;
  if (si.option_id) return false;
  if (si.skipped) return false;
  if (si.summary || si.title) return true;
  const dp = si.daily_plan;
  if (dp != null) {
    if (Array.isArray(dp)) return dp.length > 0;
    if (typeof dp === 'object') return Object.keys(dp).length > 0;
  }
  if (si.route_plan && typeof si.route_plan === 'object' && Object.keys(si.route_plan).length) return true;
  if (Array.isArray(si.days) && si.days.length) return true;
  return false;
}

/** 현재 워크플로에 맞는 명소/일정 화면으로 이동(패널 마운트 포함). */
function goToItinerarySectionForState() {
  const ws = state.itineraryWorkflowStep;
  const hasPlan = !!(state.itineraryRouteBundle || state.selectedItinerary || (state.itineraries?.length > 0));
  if (selectedItineraryLooksFinal(state.selectedItinerary) && ws !== 'meals') {
    mountItineraryStepPanel('plan');
    show('step-itinerary-plan');
    return;
  }
  if (ws === 'attractions' || (!hasPlan && state.itineraryAttractionCatalog?.length && ws !== 'meals' && ws !== 'complete')) {
    mountItineraryStepPanel('attractions');
    show('step-attractions');
    return;
  }
  mountItineraryStepPanel('plan');
  show('step-itinerary-plan');
}

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
  if (id === 'step-flights') {
    updateFlightNextButtonLabel();
  }
  if (id === 'step-rental') {
    const panel = $('#rental-search-panel');
    if (panel) {
      const isRentalCar = state.travelInput?.local_transport === 'rental_car';
      panel.classList.toggle('hidden', !isRentalCar);
      if (isRentalCar) fillRentalSearchFormFromFlight(false);
    }
  }
  if (id === 'step-attractions') {
    mountItineraryStepPanel('attractions');
  }
  if (id === 'step-itinerary-plan') {
    mountItineraryStepPanel('plan');
  }
}

function updateStepCompletedState() {
  const nodes = $$('#step-indicator .step-node');
  const steps = ['input', 'flights', 'rental', 'attractions', 'itinerary', 'accommodation', 'confirm', 'booking'];
  steps.forEach((s, i) => {
    const node = nodes[i];
    if (!node) return;
    const hasData = s === 'input' && state.travelInput
      || s === 'flights' && buildSelectedFlight()
      || s === 'rental' && (state.localTransport?.length > 0 || state.selectedLocalTransport)
      || s === 'attractions' && (state.itineraryAttractionCatalog?.length > 0 || state.selectedAttractionIds?.length > 0)
      || s === 'itinerary' && (state.itineraryRouteBundle || state.selectedItinerary || state.itineraries?.length > 0
        || state.itineraryWorkflowStep === 'meals' || state.itineraryWorkflowStep === 'complete' || state.itineraryWorkflowStep === 'legacy')
      || s === 'accommodation' && (state.accommodations?.length > 0 || state.selectedAccommodation)
      || s === 'confirm' && state.accommodations?.length > 0
      || s === 'booking' && state.selectedAccommodation;
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
      renderFlights(flightsToShow, state.flightWarnings || [], state.flightSearchApi);
      showFlightSummaryForEdit(sf);
    } else if (flightsToShow.length) {
      renderFlights(flightsToShow, state.flightWarnings || [], state.flightSearchApi);
      $('#flights-list').classList.remove('hidden');
      $('#flight-sort-bar').classList.remove('hidden');
      $('#selected-flight-summary').classList.add('hidden');
    }
  }
  if (step === 'rental' && state.localTransport?.length) {
    const panel = $('#rental-search-panel');
    if (panel) {
      const isRentalCar = state.travelInput?.local_transport === 'rental_car';
      panel.classList.toggle('hidden', !isRentalCar);
      if (isRentalCar) fillRentalSearchFormFromFlight(false);
    }
    renderRentalOptions(state.localTransport);
  }
  if (step === 'attractions') {
    mountItineraryStepPanel('attractions');
    if (state.itineraryAttractionCatalog?.length) {
      renderItineraryWorkflow({
        itinerary_step: 'select_attractions',
        attractions: state.itineraryAttractionCatalog,
        design_notes: '',
        time_ratio_note: '',
        trip_days: state.itineraryTripDays != null
          ? state.itineraryTripDays
          : ((state.travelInput?.start_date && state.travelInput?.end_date)
            ? inclusiveCalendarDays(state.travelInput.start_date, state.travelInput.end_date)
            : (state.itineraryAttractionCatalog?.length ? Math.ceil(state.itineraryAttractionCatalog.length / 3) : 1)),
      });
    }
  }
  if (step === 'itinerary') {
    mountItineraryStepPanel('plan');
    if (state.itineraryWorkflowStep === 'meals' && state.itineraryRouteBundle) {
      renderItineraryWorkflow(state.itineraryRouteBundle);
    } else if (selectedItineraryLooksFinal(state.selectedItinerary)) {
      renderItineraryWorkflow({ itinerary_step: 'complete', final_itinerary: state.selectedItinerary });
    } else if (state.itineraries?.length) {
      renderItineraries(state.itineraries);
    } else if (state.itineraryAttractionCatalog?.length) {
      const root = $('#itinerary-workflow-root');
      if (root) {
        root.innerHTML = '<p class="muted">아직 동선·맛집 계획이 없습니다. <strong>4. 명소 선택</strong>에서 명소를 고른 뒤 「경로·맛집 계획 받기」를 누르거나, 저장·불러오기로 이전 진행을 복원하세요.</p>';
      }
      updateItineraryNextButton();
    }
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
  if (stepName === 'attractions') {
    // 맛집 단계에서 명소로 돌아갈 때만 동선·맛집 초안 삭제. 완성 일정(complete)은 명소만 살펴보는 경우가 많아 상태 유지.
    if (state.itineraryWorkflowStep === 'meals') {
      state.itineraryWorkflowStep = 'attractions';
      state.itineraryRouteBundle = null;
      state.mealChoices = {};
      saveItineraryDraft();
    } else if (state.itineraryWorkflowStep !== 'complete' && state.itineraryRouteBundle) {
      state.itineraryWorkflowStep = 'attractions';
      state.itineraryRouteBundle = null;
      state.mealChoices = {};
      saveItineraryDraft();
    }
  }
  if (stepName === 'itinerary') {
    const hasPlan = !!(state.itineraryRouteBundle || state.selectedItinerary || (state.itineraries?.length > 0));
    const ws = state.itineraryWorkflowStep;
    const pastAttractions = ws === 'meals' || ws === 'complete' || ws === 'legacy';
    // 동선·맛집/확정 일정 단계였는데 본문 키가 비어 있는 저장본도 5단계로 보낸다(여기서 막으면 4↔5 이동이 막힘).
    if (!hasPlan && !pastAttractions && state.itineraryAttractionCatalog?.length) {
      navigateToStep('attractions');
      return;
    }
  }
  const sectionId = STEP_TO_SECTION[stepName];
  if (!sectionId) return;
  show(sectionId, true);
}

function showError(msg) {
  $('#error-message').textContent = msg;
  show('error');
}

/** 일정 단계에서 API 실패 시 전용 오류 화면 대신 일정 카드로 돌아가 선택·동선 상태를 유지한다. */
function showAgentError(msg, opts = {}) {
  const preferItinerary = opts.preferItinerary !== false;
  if (
    preferItinerary
    && state.itineraryAttractionCatalog?.length
    && (state.itineraryWorkflowStep === 'attractions'
      || state.itineraryWorkflowStep === 'meals'
      || state.itineraryWorkflowStep === 'complete'
      || state.itineraryWorkflowStep === 'legacy')
  ) {
    alert(msg);
    goToItinerarySectionForState();
    const st = state.itineraryWorkflowStep === 'attractions' ? 'attractions' : 'itinerary';
    refreshStepView(st);
    saveItineraryDraft();
    return;
  }
  showError(msg);
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
    end_date: form.end_date?.value || form.start_date?.value,
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
    const routeContext = {
      originInput: form.origin?.value?.trim() || '',
      destInput: form.destination?.value?.trim() || '',
      originAirportCode: state.origin_airport_code,
      destAirportCode: state.destination_airport_code,
      domesticRoute: typeof isDomesticRoute === 'function' && isDomesticRoute(
        form.origin?.value?.trim() || '',
        form.destination?.value?.trim() || '',
        state.origin_airport_code,
        state.destination_airport_code,
      ),
    };
    const airports = getDestAirportsForOrigin(originCode, form.destination?.value?.trim(), {
      useMiles: form.use_miles?.checked,
      mileageProgram: form.mileage_program?.value,
      routeContext,
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
  const form = $('#travel-form');
  const origin = form.origin?.value?.trim() || '';
  const dest = form.destination?.value?.trim() || '';
  const routeContext = {
    originInput: origin,
    destInput: dest,
    originAirportCode: state.origin_airport_code,
    destAirportCode: state.destination_airport_code,
    domesticRoute: typeof isDomesticRoute === 'function' && isDomesticRoute(
      origin, dest, state.origin_airport_code, state.destination_airport_code,
    ),
  };
  const airports = (typeof getAirportsForPlaceWithGroundRules === 'function'
    ? getAirportsForPlaceWithGroundRules(origin, 'origin', { routeContext })
    : getAirportsForCity(origin)) || [];
  const list = $('#origin-airports-list');
  list.innerHTML = airports.map(a => `
    <div class="airport-item" data-code="${a.code}">
      <span><span class="code">${a.code}</span> <span class="name">${a.name}</span></span>
      <span>차량 약 ${a.drive_hours}h</span>
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
  const routeContext = {
    originInput: form.origin?.value?.trim() || '',
    destInput: dest,
    originAirportCode: state.origin_airport_code,
    destAirportCode: state.destination_airport_code,
    domesticRoute: typeof isDomesticRoute === 'function' && isDomesticRoute(
      form.origin?.value?.trim() || '',
      dest,
      state.origin_airport_code,
      state.destination_airport_code,
    ),
  };
  const options = {
    useMiles: form.use_miles?.checked ?? false,
    mileageProgram: form.mileage_program?.value?.trim() || '',
    routeContext,
  };
  const airports = getDestAirportsForOrigin(originCode, dest, options)
    || (typeof getAirportsForPlaceWithGroundRules === 'function'
      ? getAirportsForPlaceWithGroundRules(dest, 'destination', { routeContext })
      : getAirportsForCity(dest))
    || [];
  const info = (typeof FLIGHT_INFO !== 'undefined' && FLIGHT_INFO[originCode]) || {};
  const mileageKey = typeof normalizeMileageProgram === 'function' ? normalizeMileageProgram(options.mileageProgram) : '';
  const list = $('#destination-airports-list');
  const sortedCodes = airports.map(a => a.code);
  const regionHint =
    typeof isRegionCollectionDestination === 'function' && isRegionCollectionDestination(dest)
      ? '<p class="airport-region-hint" style="margin:0 0 10px;font-size:0.9em;color:#444;line-height:1.45;">이 목적지는 <strong>여러 관광지가 묶인 지역</strong>입니다. 항공 검색용 도착 공항은 <strong>출발 공항 기준 비행 거리가 가까운 순</strong>으로 정렬했습니다. 현지에서는 렌트 등으로 루프 동선을 짜면 됩니다.</p>'
      : '';
  list.innerHTML = regionHint + airports.map((a, i) => {
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

/** 항공 건너뛰기 시 로컬 상태만 설정. false면 다구간 등으로 중단. */
function prepareFlightSkipLocalState() {
  const tt = $('#trip_type_select')?.value || 'round_trip';
  if (tt === 'multi_city') {
    alert('다구간 여정은 구간별로 항공편을 선택해야 합니다.');
    return false;
  }
  state.flightSkipped = true;
  state.selectedFlight = null;
  state.selectedOutboundFlight = null;
  state.selectedReturnFlight = null;
  state.selectedMultiCityFlights = [];
  state.flights = [];
  state.currentFlights = null;
  state.flightsByLeg = {};
  state.travelInput = buildTravelInput();
  state.trip_type = state.travelInput?.trip_type || tt;
  return true;
}

/** 항공 없이 세션에 렌트 검색 요청 (flight_skipped). 렌트 결정 화면에서 「검색」 시 호출. */
async function runSessionRentalSearchSkipFlight() {
  const tt = $('#trip_type_select')?.value || 'round_trip';
  if (tt === 'multi_city') {
    alert('다구간 여정은 구간별로 항공편을 선택해야 합니다.');
    return;
  }
  state.travelInput = buildTravelInput();
  state.trip_type = state.travelInput?.trip_type || tt;
  show('loading');
  try {
    const data = await callAgent(baseSessionPayload({ selected_flight: null }));
    if (data?.error) throw new Error(data.error);
    if (data?.step === 'rental') {
      state.localTransport = normalizeLocalTransport(data?.local_transport);
      renderRentalOptions(state.localTransport);
      show('step-rental');
      fillRentalSearchFormFromFlight(true);
      return;
    }
    if (data?.step === 'accommodation_and_transport') {
      state.accommodations = Array.isArray(data?.accommodations) ? data.accommodations : [];
      state.localTransport = normalizeLocalTransport(data?.local_transport);
      renderAccommodations(state.accommodations);
      renderRentalOptions(state.localTransport);
      show('step-accommodation');
      return;
    }
    applyItineraryResponse(data);
  } catch (err) {
    showError(err.message);
  }
}

function showRentalDecide(from) {
  state.rentalDecideFrom = from === 'no_flight' ? 'no_flight' : 'after_flight';
  const lead = $('#rental-decide-lead');
  if (lead) {
    lead.textContent = from === 'no_flight'
      ? '항공 단계를 건너뛰었습니다. 렌트카·대중교통 검색을 진행할지, 여행 일정 단계로 바로 갈지 선택하세요.'
      : '선택한 항공을 반영해 렌트카·대중교통 옵션을 검색할 수 있습니다. 검색할지 여행 일정으로 바로 갈지 선택하세요.';
  }
  show('step-rental-decide');
}

async function executeRentalSearchFromDecide() {
  if (state.flightSkipped) {
    await runSessionRentalSearchSkipFlight();
  } else {
    await advanceToLocalTransportStep();
  }
}

function validateTravelDateRange() {
  const startVal = $('#travel-form').start_date?.value;
  const endVal = $('#travel-form').end_date?.value;
  if (startVal && endVal && endVal < startVal) {
    alert('귀환일은 출발일 이후로 선택해 주세요.');
    return false;
  }
  return true;
}

/** intent: 'flights' | 'no_flights' — 여행 정보에서 공항 선택 후 이어짐 */
async function startTravelFlow(intent) {
  if (!validateTravelDateRange()) return;
  state.travelPrimaryIntent = intent;
  if (intent === 'no_flights') {
    const tt = $('#trip_type_select')?.value || 'round_trip';
    if (tt === 'multi_city') {
      alert('다구간 여정은 구간별 항공 선택이 필요합니다. 「항공편 검색·선택」으로 진행해 주세요.');
      return;
    }
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
  await finishTravelAirportFlow();
}

async function finishTravelAirportFlow() {
  const intent = state.travelPrimaryIntent;
  if (intent === 'no_flights') {
    if (!prepareFlightSkipLocalState()) return;
    showRentalDecide('no_flight');
    return;
  }
  state.flightSkipped = false;
  await doFlightSearch();
}

async function doFlightSearch(leg) {
  state.flightSkipped = false;
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
    state.flightSearchApi = typeof data?.flight_search_api === 'string' ? data.flight_search_api : '';
    renderFlights(flights, warnings, state.flightSearchApi);
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

$('#travel-form').addEventListener('submit', (e) => {
  e.preventDefault();
});

$('#btn-travel-pick-flights')?.addEventListener('click', () => startTravelFlow('flights'));
$('#btn-travel-skip-flights')?.addEventListener('click', () => startTravelFlow('no_flights'));

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

$('#btn-next-origin-airports').addEventListener('click', async () => {
  if (!state.origin_airport_code) { alert('공항을 선택해 주세요.'); return; }
  if (needDestAirport() && !state.destination_airport_code) {
    renderDestAirports();
    show('step-destination-airports');
  } else {
    await finishTravelAirportFlow();
  }
});

$('#btn-next-destination-airports').addEventListener('click', async () => {
  if (!state.destination_airport_code) { alert('공항을 선택해 주세요.'); return; }
  await finishTravelAirportFlow();
});

$('#btn-rental-decide-search')?.addEventListener('click', () => executeRentalSearchFromDecide());
$('#btn-rental-decide-skip')?.addEventListener('click', () => skipRentalToItinerary());
$('#btn-back-rental-decide')?.addEventListener('click', () => {
  if (state.rentalDecideFrom === 'no_flight') show('step-input');
  else show('step-flights');
});

function fmtFlightDateTime(iso) {
  if (!iso) return '';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return iso;
  return `${m[2]}/${m[3]} ${m[4]}:${m[5]}`;
}

function renderFlights(flights, warnings, searchApiLabel) {
  const fList = flights !== undefined && flights !== null ? flights : state.currentFlights;
  const warns = warnings !== undefined && warnings !== null ? warnings : (state.flightWarnings || []);
  const apiLabel = searchApiLabel !== undefined && searchApiLabel !== null ? searchApiLabel : (state.flightSearchApi || '');
  if (searchApiLabel !== undefined && searchApiLabel !== null) {
    state.flightSearchApi = searchApiLabel;
  }
  const list = $('#flights-list');
  const warnEl = $('#flight-warnings');
  const mockEl = $('#flight-mock-notice');
  const apiEl = $('#flight-search-api');
  const sortBar = $('#flight-sort-bar');
  const stepTitle = $('#step-flights-title');
  if (apiEl) {
    if (apiLabel) {
      apiEl.textContent = '이번 검색에 사용된 API: ' + apiLabel;
      apiEl.classList.remove('hidden');
    } else {
      apiEl.textContent = '';
      apiEl.classList.add('hidden');
    }
  }

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
  if (flights !== undefined && flights !== null) {
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
    const ret = isRt ? (f.return || null) : null;
    const destLabel = (ob?.destination_label ? `${ob.destination || ''} (${ob.destination_label})` : ob?.destination) || (f.destination_label ? `${f.destination || ''} (${f.destination_label})` : f.destination) || '';
    const route = isRt ? `${ob?.origin || ''} ⇌ ${destLabel}` : `${f.origin || ''} → ${destLabel}`;
    const timeRange = isRt
      ? `${fmtFlightDateTime(ob?.departure)} ~ ${fmtFlightDateTime((ret && ret.arrival) || ob?.arrival)}`
      : `${fmtFlightDateTime(f.departure)} ~ ${fmtFlightDateTime(f.arrival)}`;
    const durOb = ob?.duration_hours || 0;
    const durRet = ret?.duration_hours || 0;
    const totalDur = isRt ? durOb + durRet : durOb;
    const duration = totalDur ? ` · 약 ${totalDur}시간` : '';
    const priceDisplay = (f.price_krw ? f.price_krw.toLocaleString() + '원' : (f.miles_required || 0) + '마일') + (isRt ? ' (왕복)' : '');
    const mileageBadge = f.mileage_eligible ? '<span class="flight-badge mileage">마일리지 적립</span>' : '';
    const mockBadge = (ob?.source === 'mock_reference' || ob?.source === 'mock' || f.source === 'mock')
      ? '<span class="flight-badge" style="background:#fff3cd; color:#856404; margin-left: 5px;">예시(Mock) 참고용</span>'
      : '';

    // Segments and layovers details
    let detailsHtml = '';
    const segsForDetails = isRt ? [...(ob?.segments || []), ...(ret?.segments || [])] : (f.segments || []);
    if (segsForDetails.length > 0) {
      detailsHtml += `<div class="flight-details hidden" id="flight-details-${i}" style="margin-top: 1rem; padding: 1rem; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.9em; background: rgba(0,0,0,0.15); border-radius: 0 0 8px 8px;">`;

      let isReturnFlightStarted = false;
      const outboundDateStart = ob?.departure ? ob.departure.substring(0, 10) : "";
      const obSegCount = (ob?.segments || []).length;

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
          } else if (dAirport.includes(ob?.destination || '') || (seg.departure_airport?.id || '') === (ob?.destination || '')) {
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

    const routeDisplay = isRt ? route : (state.travelInput?.trip_type === 'round_trip' ? `${ob?.origin || ''} ⇌ ${destLabel}` : route);

    return `
    <div class="option-item" data-idx="${i}" style="flex-direction: column; align-items: stretch; padding: 0;">
      <div class="flight-summary" style="padding: 1rem;">
        <h3>${ob?.airline || '항공사'} ${ob?.flight_number || ''} ${mileageBadge}${mockBadge}</h3>
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

/** 항공 선택이 모두 끝났는지 (렌트카/대중교통 단계로 자동 진행 가능). */
function isLocalTransportSelectionComplete() {
  const tt = state.trip_type || $('#trip_type_select')?.value || 'round_trip';
  if (tt === 'one_way') return !!state.selectedOutboundFlight;
  if (tt === 'round_trip') return !!(state.selectedOutboundFlight && state.selectedReturnFlight);
  if (tt === 'multi_city') {
    const mc = state.multi_cities || state.travelInput?.multi_cities || [];
    const m = (state.flightLeg || '').match(/multi_city_(\d+)/);
    const idx = m ? parseInt(m[1], 10) : 0;
    return !!(mc.length && idx === mc.length - 1 && state.selectedMultiCityFlights?.[idx]);
  }
  return false;
}

/** 항공 확정 후 세션에 렌트카/대중교통 검색 요청 → step-rental 등. */
async function advanceToLocalTransportStep() {
  applyFlightDatesToTravelForm();
  state.travelInput = buildTravelInput();
  state.selectedFlight = buildSelectedFlight();
  if (!state.flightSkipped && !state.selectedFlight) {
    alert('항공편 선택을 완료해 주세요.');
    return false;
  }
  show('loading');
  try {
    const payload = baseSessionPayload({ selected_flight: state.selectedFlight });
    let data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);

    if (data?.step === 'rental') {
      state.localTransport = normalizeLocalTransport(data?.local_transport);
      renderRentalOptions(state.localTransport);
      show('step-rental');
      fillRentalSearchFormFromFlight(true);
      return true;
    }
    if (Array.isArray(data?.flights) && data.flights.length > 0 && !data?.step) {
      const hasCompleteRoundTrip = state.trip_type === 'round_trip' && state.selectedOutboundFlight && state.selectedReturnFlight;
      if (hasCompleteRoundTrip) {
        const retryData = await callAgent(payload);
        if (retryData?.step === 'rental') {
          state.localTransport = normalizeLocalTransport(retryData?.local_transport);
          renderRentalOptions(state.localTransport);
          show('step-rental');
          fillRentalSearchFormFromFlight(true);
          return true;
        }
        if (retryData?.error) throw new Error(retryData.error);
        throw new Error('다음 단계로 진행할 수 없습니다. 다시 시도해 주세요.');
      }
      state.flights = data.flights;
      state.flightWarnings = data?.warnings || [];
      state.flightSearchApi = typeof data?.flight_search_api === 'string' ? data.flight_search_api : '';
      if (state.trip_type === 'round_trip' && state.selectedOutboundFlight && !state.selectedReturnFlight) {
        state.flightLeg = 'return';
        state.selectedReturnFlight = null;
      }
      state.flightsByLeg[state.flightLeg] = data.flights;
      renderFlights(data.flights, state.flightWarnings, state.flightSearchApi);
      $('#flights-list').classList.remove('hidden');
      $('#flight-sort-bar').classList.remove('hidden');
      $('#selected-flight-summary').classList.add('hidden');
      if (state.flightLeg === 'return') state.selectedReturnFlight = null;
      show('step-flights');
      return true;
    }
    if (data?.step === 'accommodation_and_transport') {
      state.accommodations = Array.isArray(data?.accommodations) ? data.accommodations : [];
      state.localTransport = normalizeLocalTransport(data?.local_transport);
      renderAccommodations(state.accommodations);
      renderRentalOptions(state.localTransport);
      show('step-accommodation');
      return true;
    }

    applyItineraryResponse(data);
    return true;
  } catch (err) {
    showError(err.message);
    return false;
  }
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

  if (isLocalTransportSelectionComplete()) {
    showRentalDecide('after_flight');
  }
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

  showRentalDecide('after_flight');
});

function isoToDatetimeLocal(iso) {
  if (!iso || typeof iso !== 'string') return '';
  const s = iso.trim().replace(' ', 'T');
  return s.length >= 16 ? s.slice(0, 16) : '';
}

/** YYYY-MM-DDTHH:MM(:SS)? → 로컬 Date (타임존 접미사 없을 때 구성요소 파싱). */
function parseIsoLocalToDate(iso) {
  if (!iso || typeof iso !== 'string') return null;
  const m = iso.trim().replace(' ', 'T').match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/
  );
  if (!m) return null;
  const y = +m[1], mo = +m[2] - 1, d = +m[3], h = +m[4], mi = +m[5], s = +(m[6] || 0);
  const dt = new Date(y, mo, d, h, mi, s);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function formatDatetimeLocalFromDate(dt) {
  if (!dt) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

/** 도착 +1h → 픽업, 출발 -2h → 반납 */
function rentalPickupFromArrival(iso) {
  const dt = parseIsoLocalToDate(iso);
  if (!dt) return isoToDatetimeLocal(iso);
  dt.setHours(dt.getHours() + 1);
  return formatDatetimeLocalFromDate(dt);
}

function rentalDropoffBeforeDeparture(iso) {
  const dt = parseIsoLocalToDate(iso);
  if (!dt) return isoToDatetimeLocal(iso);
  dt.setHours(dt.getHours() - 2);
  return formatDatetimeLocalFromDate(dt);
}

/** 항공 확정 일정 → 렌트 검색 폼 (force면 항상 덮어씀). */
function fillRentalSearchFormFromFlight(force) {
  const panel = $('#rental-search-panel');
  if (!panel || panel.classList.contains('hidden')) return;
  const pEl = $('#rental-pickup-dt');
  const dEl = $('#rental-dropoff-dt');
  const iEl = $('#rental-pickup-iata');
  if (!pEl || !dEl) return;
  if (!force && pEl.value) return;
  const sf = state.selectedFlight || buildSelectedFlight();
  const ti = state.travelInput;
  let iata = (ti?.destination_airport_code || '').toString().toUpperCase().slice(0, 3);
  if (iata.length !== 3 && sf?.outbound?.destination) {
    iata = String(sf.outbound.destination).toUpperCase().slice(0, 3);
  }
  if (sf?.legs?.length) {
    const first = sf.legs[0];
    const last = sf.legs[sf.legs.length - 1];
    const arr = first.arrival || first.departure;
    if (arr) pEl.value = rentalPickupFromArrival(arr);
    const dep = last.departure || last.arrival;
    if (dep) dEl.value = rentalDropoffBeforeDeparture(dep);
    const ld = (first.destination || '').toString().toUpperCase().slice(0, 3);
    if (iEl && ld.length === 3) iEl.value = ld;
    return;
  }
  if (iEl && iata.length === 3) iEl.value = iata;
  if (sf?.outbound?.arrival) pEl.value = rentalPickupFromArrival(sf.outbound.arrival);
  else if (ti?.start_date) pEl.value = rentalPickupFromArrival(`${ti.start_date}T12:00`);
  if (sf?.return?.departure) dEl.value = rentalDropoffBeforeDeparture(sf.return.departure);
  else if (ti?.end_date) dEl.value = rentalDropoffBeforeDeparture(`${ti.end_date}T10:00`);
}

function escapeHtml(str) {
  if (str == null || str === '') return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 일반 텍스트를 이스케이프한 뒤 http(s) URL을 새 탭 링크로 감싼다. */
function linkifyUrlsInPlainText(text) {
  if (text == null || text === '') return '';
  const s = String(text);
  const re = /(https?:\/\/[^\s<]+)/gi;
  let out = '';
  let last = 0;
  let m;
  while ((m = re.exec(s)) !== null) {
    out += escapeHtml(s.slice(last, m.index));
    const url = m[1];
    const href = escapeHtml(url);
    out += `<a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a>`;
    last = m.index + url.length;
  }
  out += escapeHtml(s.slice(last));
  return out;
}

/**
 * 설명에 들어 있는 google_maps_url과 동일한 URL 직후에 붙은 중복 라벨 "Google Maps" 한 번만 제거.
 * (문장 안 "Google Maps 기준 …" 등은 유지)
 */
function stripRedundantGoogleMapsAfterMapsUrl(text, mapsUrl) {
  if (text == null || text === '') return '';
  const s = String(text);
  const u = mapsUrl && String(mapsUrl).trim();
  if (!u) return s;
  const idx = s.indexOf(u);
  if (idx === -1) return s;
  const after = idx + u.length;
  const rest = s.slice(after);
  const re = /^\s*[,;:]?\s*Google\s*Maps(?:\s*[.,;:!?])?(?!\s+\p{L})/u;
  const m = rest.match(re);
  if (!m) return s;
  return (s.slice(0, after) + rest.slice(m[0].length)).replace(/\n{3,}/g, '\n\n').trim();
}

function normalizeLineForMapsCheck(line) {
  return String(line)
    .normalize('NFKC')
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .trim();
}

/** 마크다운·목록 꾸밈을 벗겨 "Google Maps" 단독 줄인지 판별할 때 사용 */
function stripDecorationsForMapsStandaloneLine(line) {
  let t = normalizeLineForMapsCheck(line);
  t = t.replace(/^[`"'「」『』【】\[\]()]+|[`"'「」『』【】\[\]()]+$/g, '');
  t = t.replace(/^\s*>\s*/, '');
  t = t.replace(/^\s*[-*•]\s+/, '');
  t = t.replace(/^\s*\d+[.)]\s+/, '');
  t = t.replace(/^\*+\s*|\s*\*+$/g, '');
  t = t.replace(/^_+\s*|\s*_+$/g, '');
  t = t.replace(/^#{1,6}\s+/, '');
  return t.trim();
}

function lineIsStandaloneGoogleMapsLabel(line) {
  const t = stripDecorationsForMapsStandaloneLine(line);
  return /^[,;:\s]*Google\s*Maps\.?[,;:\s]*$/i.test(t);
}

/** 한 줄에 "Google Maps"만 공백으로 두 번 나온 경우 한 번으로 합침 */
function collapseInlineDuplicateGoogleMaps(text) {
  return String(text).replace(
    /\bGoogle\s*Maps\b(\s*[.,;:!?])?\s+\bGoogle\s*Maps\b(\s*[.,;:!?])?/gi,
    'Google Maps',
  );
}

/**
 * 줄 전체가 "Google Maps"(또는 **Google Maps** 등)뿐인 줄은 전부 제거.
 * 카드에 지도 링크 행이 따로 있으므로 본문에 라벨만 있는 줄은 의미 없음.
 * 문장 안 "Google Maps 기준 …" 는 줄 전체가 아니므로 유지.
 */
function stripStandaloneGoogleMapsLabelLines(text) {
  if (text == null || text === '') return '';
  let s = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  s = s.replace(/\u2028/g, '\n').replace(/\u2029/g, '\n');
  s = s.replace(/<br\s*\/?>/gi, '\n');
  s = s.replace(/&lt;br\s*\/?&gt;/gi, '\n');
  const lines = s.split('\n');
  const out = [];
  for (const line of lines) {
    if (lineIsStandaloneGoogleMapsLabel(line)) continue;
    out.push(line);
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

function attractionDescriptionToString(raw) {
  if (raw == null) return '';
  if (typeof raw === 'string') return raw;
  if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw);
  return '';
}

function prepareAttractionDescription(text, mapsUrl) {
  let s = attractionDescriptionToString(text);
  s = stripRedundantGoogleMapsAfterMapsUrl(s, mapsUrl);
  s = collapseInlineDuplicateGoogleMaps(s);
  s = stripStandaloneGoogleMapsLabelLines(s);
  return s;
}

/** 서버 구버전·저장 JSON에 남은 잡음 제거. 로드·API 응답 시 in-place로 description 정리 */
function sanitizeAttractionCatalogInPlace(catalog) {
  if (!Array.isArray(catalog)) return;
  for (const a of catalog) {
    if (!a || typeof a !== 'object') continue;
    const gm = (a.google_maps_url && String(a.google_maps_url).trim()) || '';
    const cleaned = prepareAttractionDescription(a.description, gm);
    if (cleaned !== a.description) a.description = cleaned;
  }
}

/** 세션이 local_transport를 문자열·BOM·앞뒤 잡음과 함께 줄 때도 배열로 복원 */
function normalizeLocalTransport(lt) {
  if (Array.isArray(lt)) return lt;
  if (lt == null) return [];
  if (typeof lt === 'string') {
    let s = lt.trim();
    if (s.charCodeAt(0) === 0xfeff) s = s.slice(1).trim();
    if (!s) return [];
    try {
      const p = JSON.parse(s);
      return Array.isArray(p) ? p : [];
    } catch {
      const i = s.indexOf('[');
      if (i >= 0) {
        try {
          const p = JSON.parse(s.slice(i));
          return Array.isArray(p) ? p : [];
        } catch { /* ignore */ }
      }
    }
    return [];
  }
  return [];
}

function renderRentalOptions(items) {
  const list = $('#rental-list');
  if (!list) return;
  const panel = $('#rental-search-panel');
  if (panel) {
    const isRentalCar = state.travelInput?.local_transport === 'rental_car';
    panel.classList.toggle('hidden', !isRentalCar);
  }
  const isRental = state.travelInput?.local_transport === 'rental_car';
  const rows = normalizeLocalTransport(items);
  const selectHint = $('#rental-select-hint');
  if (selectHint) selectHint.classList.add('hidden');
  if (isRental && rows.length === 0) {
    list.innerHTML = '<p class="rental-empty muted" role="status">렌트카 목록이 비어 있습니다. 픽업·반납 일시와 공항 코드(IATA)를 확인한 뒤 「이 일정으로 다시 검색」을 눌러 주세요. 계속 비면 서버에서 렌트 MCP 응답이 JSON 배열로 오는지 확인하세요.</p>';
    state.selectedLocalTransport = null;
    const countEl = $('#rental-result-count');
    if (countEl) countEl.textContent = '';
    const discEl = $('#rental-price-disclaimer');
    if (discEl) discEl.classList.add('hidden');
    updateRentalBookingButton();
    return;
  }
  if (isRental && rows.length > 0 && selectHint) selectHint.classList.remove('hidden');
  list.innerHTML = rows.map((opt, i) => {
    if (isRental && (opt.image_url || opt.vehicle_name || opt.booking_url || opt.offer_kind === 'amadeus_transfer' || opt.offer_kind === 'serpapi_self_drive' || opt.offer_kind === 'vehicle_class_guide' || opt.offer_kind === 'self_drive_compare' || opt.offer_kind === 'affiliate' || opt.offer_kind === 'info')) {
      const seatsLabel = opt.seats ? ` (${opt.seats}인승)` : '';
      const titleRaw = opt.provider ? `${opt.provider} - ${opt.car_type || ''}${seatsLabel}` : (opt.car_type || `옵션 ${i + 1}`) + seatsLabel;
      const title = escapeHtml(titleRaw);
      const features = escapeHtml(Array.isArray(opt.features) ? opt.features.join(' · ') : (opt.features || ''));
      const recommendedBadge = opt.recommended ? '<span class="rental-badge recommended">여행가방 추천</span>' : '';
      const kind = opt.offer_kind || '';
      const kindBadge = kind === 'amadeus_transfer'
        ? '<span class="rental-badge">트랜스퍼 견적</span>'
        : kind === 'serpapi_self_drive'
          ? '<span class="rental-badge">셀프 드라이브 후보</span>'
          : kind === 'vehicle_class_guide'
            ? '<span class="rental-badge">차급·스펙</span>'
            : kind === 'self_drive_compare'
              ? '<span class="rental-badge">셀프 드라이브 비교</span>'
              : kind === 'info'
                ? '<span class="rental-badge">안내</span>'
                : kind === 'affiliate'
                  ? '<span class="rental-badge">제휴</span>'
                  : '';
      const imgHtml = opt.image_url
        ? `<img src="${String(opt.image_url).replace(/"/g, '%22')}" alt="${escapeHtml(opt.vehicle_name || opt.car_type || '')}" class="rental-card-img" loading="lazy">`
        : '';
      const vn = escapeHtml(opt.vehicle_name || '');
      const od = escapeHtml(opt.description || '');
      const detailHtml = (opt.description || opt.vehicle_name) ? `<p class="rental-desc">${vn}${od ? ' · ' + od : ''}</p>` : '';
      const luggageHtml = opt.luggage_capacity ? `<span class="rental-luggage">수하물: ${escapeHtml(opt.luggage_capacity)}</span>` : '';
      const priceBasis = escapeHtml(opt.price_basis || '');
      const bookingLabel = kind === 'self_drive_compare'
        ? '공항 전체 비교 (EB)'
        : kind === 'vehicle_class_guide'
          ? '이 차급·일정 (EB)'
          : kind === 'serpapi_self_drive'
            ? '가격·차종 확인(출처)'
            : kind === 'affiliate'
              ? 'Travelpayouts 제휴 열기'
              : (opt.provider === 'EconomyBookings' ? 'EconomyBookings 열기' : '예약·약관 확인');
      const safeBooking = typeof opt.booking_url === 'string' && /^https?:\/\//i.test(opt.booking_url) ? opt.booking_url : '';
      const bookingBtn = safeBooking
        ? `<a href="${safeBooking.replace(/"/g, '%22')}" target="_blank" rel="noopener" class="btn-booking" onclick="event.stopPropagation()">${bookingLabel}</a>`
        : '';
      const liveEb = kind === 'self_drive_compare' && typeof opt.eb_cars_results_url === 'string' && /^https?:\/\//i.test(opt.eb_cars_results_url)
        ? opt.eb_cars_results_url
        : '';
      const liveEbBtn = liveEb
        ? `<a href="${liveEb.replace(/"/g, '%22')}" target="_blank" rel="noopener" class="btn-booking btn-eb-live" onclick="event.stopPropagation()">실시간 차량·가격 (EB)</a>`
        : '';
      const orig = (opt.price_original_amount && opt.price_original_currency)
        ? ` <span class="rental-original-price">(${escapeHtml(String(opt.price_original_amount))} ${escapeHtml(String(opt.price_original_currency))})</span>`
        : '';
      const snipRaw = opt.price_snippet_raw ? `<span class="rental-snippet-price">스니펫: ${escapeHtml(opt.price_snippet_raw)}</span>` : '';
      const srcLine = opt.source_label ? `<p class="rental-source">${escapeHtml(opt.source_label)}</p>` : '';
      const schedLine = opt.rental_schedule_line ? `<p class="rental-schedule">${escapeHtml(opt.rental_schedule_line)}</p>` : '';
      const locLine = [opt.pickup_location, opt.dropoff_location].filter(Boolean).map((x) => escapeHtml(x)).join(' → ');
      const priceEst = opt.price_is_estimate && opt.price_total_krw ? '약 ' : '';
      return `
        <div class="option-item rental-card" data-idx="${i}">
          <div class="rental-card-media">${imgHtml}</div>
          <div class="rental-card-body">
            <h3>${title} ${kindBadge} ${recommendedBadge}</h3>
            ${opt.price_label_ko ? `<p class="rental-price-headline">${escapeHtml(opt.price_label_ko)}</p>` : ''}
            ${detailHtml}
            ${features ? `<p class="rental-features">${features}</p>` : ''}
            ${srcLine}
            ${luggageHtml}
            ${schedLine}
            <p class="rental-location">${locLine}</p>
            <div class="rental-footer">
              ${opt.price_total_krw ? `<span class="price">${priceEst}${opt.price_total_krw.toLocaleString()}원</span>${orig}${snipRaw}` : '<span class="rental-no-price">가격: 링크에서 확인</span>'}
              ${bookingBtn}${liveEbBtn}
            </div>
            ${priceBasis ? `<div class="rental-price-basis">${priceBasis}</div>` : ''}
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
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(desc)}</p>
      </div>
    `;
  }).join('');
  list.querySelectorAll('.option-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target?.closest('.btn-booking')) return;
      list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.selectedLocalTransport = rows[parseInt(el.dataset.idx, 10)];
      updateRentalBookingButton();
    });
  });
  let pickIdx = 0;
  if (rows && rows.length > 0) {
    const withUrl = rows.findIndex(o => o.booking_url);
    pickIdx = withUrl >= 0 ? withUrl : 0;
    state.selectedLocalTransport = rows[pickIdx];
    list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
    list.querySelector(`.option-item[data-idx="${pickIdx}"]`)?.classList.add('selected');
  }
  // 결과 수 및 면책 표시
  const countEl = $('#rental-result-count');
  if (countEl) countEl.textContent = isRental && rows.length ? `총 ${rows.length}건` : '';
  const discEl = $('#rental-price-disclaimer');
  if (discEl) discEl.classList.toggle('hidden', !isRental || !rows.length);
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

const PRACTICAL_DETAIL_LABELS = {
  parking: '주차·도로 (거점·승용차 분)',
  cable_car_lift: '케이블카·리프트',
  walking_hiking: '도보·하이킹',
  fees_other: '입장료·톨·기타',
  reservation_note: '예약·개방·운영시간',
  tips: '준비·팁',
};

function renderPracticalDetailsHtml(pd) {
  if (!pd || typeof pd !== 'object') return '';
  return Object.keys(PRACTICAL_DETAIL_LABELS).map((k) => {
    const v = pd[k];
    if (v == null || String(v).trim() === '') return '';
    const raw = String(v);
    const dd = k === 'fees_other' ? linkifyUrlsInPlainText(raw) : escapeHtml(raw);
    return `<dt>${escapeHtml(PRACTICAL_DETAIL_LABELS[k])}</dt><dd>${dd}</dd>`;
  }).join('');
}

function getRestaurantOptionsForDay(routeBundle, dateStr) {
  const ds = (routeBundle.route_plan?.daily_schedule || []).find(x => x.date === dateStr);
  if (!ds) return [];
  const am = ds.morning_attraction_id;
  const pm = ds.afternoon_attraction_id;
  const extras = Array.isArray(ds.extra_attraction_ids) ? ds.extra_attraction_ids : [];
  const rba = routeBundle.restaurants_by_attraction || {};
  const list = [];
  [am, pm, ...extras].filter(Boolean).forEach((aid) => {
    (rba[aid] || []).forEach((r) => {
      if (r && r.id && !list.find(x => x.id === r.id)) list.push(r);
    });
  });
  return list.sort((a, b) => (Number(b.rating) || 0) - (Number(a.rating) || 0));
}

function collectAndValidateMealChoices() {
  const bundle = state.itineraryRouteBundle;
  const dates = bundle?.trip_dates || [];
  const root = $('#itinerary-workflow-root');
  const mc = {};
  for (const d of dates) {
    const lf = root?.querySelector(`select[data-date="${d}"][data-meal="lunch"][data-rank="first"]`)?.value;
    const ls = root?.querySelector(`select[data-date="${d}"][data-meal="lunch"][data-rank="second"]`)?.value;
    const df = root?.querySelector(`select[data-date="${d}"][data-meal="dinner"][data-rank="first"]`)?.value;
    const ds = root?.querySelector(`select[data-date="${d}"][data-meal="dinner"][data-rank="second"]`)?.value;
    if (!lf || !ls || !df || !ds) {
      alert(`${d} 날짜의 점심·저녁 1순위·2순위를 모두 선택해 주세요.`);
      return false;
    }
    if (lf === ls || df === ds) {
      alert(`${d}: 1순위와 2순위는 서로 다른 곳을 선택해 주세요.`);
      return false;
    }
    mc[d] = {
      lunch: { first: lf, second: ls },
      dinner: { first: df, second: ds },
    };
  }
  state.mealChoices = mc;
  return true;
}

/** 맛집 단계에서 선택만 바꾼 경우(아직 「일정 확정」 전) draft에 반영 */
function snapshotMealChoicesFromDom() {
  const bundle = state.itineraryRouteBundle;
  const dates = bundle?.trip_dates || [];
  const root = $('#itinerary-workflow-root');
  if (!dates.length || !root) return;
  const mc = { ...state.mealChoices };
  for (const d of dates) {
    const lf = root.querySelector(`select[data-date="${d}"][data-meal="lunch"][data-rank="first"]`)?.value;
    const ls = root.querySelector(`select[data-date="${d}"][data-meal="lunch"][data-rank="second"]`)?.value;
    const df = root.querySelector(`select[data-date="${d}"][data-meal="dinner"][data-rank="first"]`)?.value;
    const ds = root.querySelector(`select[data-date="${d}"][data-meal="dinner"][data-rank="second"]`)?.value;
    if (lf || ls || df || ds) {
      mc[d] = {
        lunch: { first: lf || '', second: ls || '' },
        dinner: { first: df || '', second: ds || '' },
      };
    }
  }
  state.mealChoices = mc;
}

function updateItineraryNextButton() {
  const btn = $('#btn-next-itineraries');
  const btnBack = $('#btn-back-itineraries');
  if (!btn) return;
  const ws = state.itineraryWorkflowStep;
  if (ws === 'attractions') {
    btn.textContent = '경로·맛집 계획 받기';
    btn.disabled = !(state.selectedAttractionIds?.length > 0);
    if (btnBack) btnBack.textContent = '뒤로 (렌트카/대중교통)';
  } else if (ws === 'meals') {
    btn.textContent = '일정 확정';
    btn.disabled = false;
    if (btnBack) btnBack.textContent = '뒤로 (명소 선택)';
  } else if (ws === 'complete') {
    btn.textContent = '다음 (숙소 선택)';
    btn.disabled = false;
    if (btnBack) btnBack.textContent = '뒤로 (명소 선택)';
  } else if (ws === 'legacy') {
    btn.textContent = '다음 (숙소 선택)';
    btn.disabled = !state.selectedItinerary;
    if (btnBack) btnBack.textContent = '뒤로 (명소 선택)';
  } else {
    btn.textContent = '다음';
    btn.disabled = true;
    if (btnBack) btnBack.textContent = '뒤로';
  }
}

function renderItineraryWorkflow(data) {
  const root = $('#itinerary-workflow-root');
  if (!root) return;
  const step = data?.itinerary_step;
  if (step === 'select_attractions') {
    if (selectedItineraryLooksFinal(state.selectedItinerary)) {
      state.itineraryWorkflowStep = 'complete';
    } else {
      state.itineraryWorkflowStep = 'attractions';
    }
    const ats = data.attractions || [];
    sanitizeAttractionCatalogInPlace(ats);
    const note = data.time_ratio_note || '';
    const design = data.design_notes || '';
    const tripDays = data.trip_days || '';
    root.innerHTML = `
      <div class="itinerary-phase">
        <p class="muted">${escapeHtml(note)}</p>
        <p>${escapeHtml(design)}</p>
        <p><strong>여행 일수(포함): ${escapeHtml(String(tripDays))}일</strong> · 후보 명소 ${ats.length}곳(일수×3) — 사진·주차·리프트·도보 시간 등을 비교해 선택하세요.</p>
        <p class="muted" style="font-size:0.88rem;line-height:1.45;">사진은 서버가 <strong>위키백과(영·이)</strong> 문서 썸네일·<strong>Wikimedia Commons</strong>를 검색해, 명소명과 맞는 후보만 붙입니다. 카드마다 다른 사진을 쓰도록 중복도 줄입니다. 매칭이 어려우면 사진을 비우고 안내 문구만 둡니다(잘못된 풍경 사진 대신). 선택 시 <strong>SerpApi</strong> Google 이미지 보강이 켜져 있으면 추가로 시도합니다. 구글맵 <strong>사용자 리뷰 사진</strong>은 API·라이선스 이슈로 자동 수집하지 않습니다.</p>
        <div style="margin: 0.5rem 0; text-align: right;">
          <button type="button" id="btn-select-all-attrs" class="secondary" style="padding: 0.4rem 0.8rem; font-size: 0.85rem; margin: 0;">전체 선택 / 해제</button>
        </div>
        <div class="attraction-checklist">
          ${ats.map((a, index) => {
            const id = escapeHtml(a.id || '');
            const checked = state.selectedAttractionIds?.includes(a.id) ? 'checked' : '';
            const img = (a.image_url && String(a.image_url).trim())
              ? `<div class="attraction-card__media"><img src="${escapeHtml(a.image_url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="var m=this.closest('.attraction-card__media');if(m){m.classList.add('attraction-card__media--empty');}this.style.display='none';" /></div>`
              : `<div class="attraction-card__media attraction-card__media--empty" role="img" aria-label="대표 사진 없음"><span class="attraction-card__media-placeholder">대표 사진 없음</span></div>`;
            const credit = a.image_credit ? `<p class="attraction-card__credit muted">${escapeHtml(a.image_credit)}</p>` : '';
            const pHtml = renderPracticalDetailsHtml(a.practical_details);
            const owRaw = (a.official_website && String(a.official_website).trim()) || '';
            const gmRaw = (a.google_maps_url && String(a.google_maps_url).trim()) || '';
            const sameUrl = owRaw && gmRaw && owRaw === gmRaw;
            const web = owRaw.startsWith('http')
              ? `<a href="${escapeHtml(owRaw)}" target="_blank" rel="noopener noreferrer">${sameUrl ? '공식 웹 · 지도' : '공식 웹'}</a>` : '';
            const gmap = !sameUrl && gmRaw.startsWith('http')
              ? `<a href="${escapeHtml(gmRaw)}" target="_blank" rel="noopener noreferrer" aria-label="Google Maps">지도</a>` : '';
            const linksRow = (web || gmap)
              ? `<p class="attraction-card__links muted" style="font-size:0.88rem;">${[web, gmap].filter(Boolean).join(' · ')}</p>`
              : '';
            const hubNm = a.nearest_hub_display_name && String(a.nearest_hub_display_name).trim();
            const hubMin = a.drive_minutes_from_nearest_hub;
            const hubRow = hubNm && hubMin != null && hubMin !== ''
              ? `<p class="attraction-card__hub muted" style="font-size:0.9rem;margin:0.25rem 0 0;">숙소·일정 참고: <strong>${escapeHtml(hubNm)}</strong>에서 승용차 약 ${escapeHtml(String(hubMin))}분 (서버 Directions 기준)</p>`
              : '';
            return `<label class="attraction-card option-item">
              <div class="attraction-card__pick"><input type="checkbox" class="attr-pick" value="${id}" ${checked} /></div>
              ${img}
              <div class="attraction-card__body">
                <h3 class="attraction-card__title">${index + 1}. ${escapeHtml(a.name || '')} <span class="muted">(${escapeHtml(a.category || '')})</span></h3>
                ${hubRow}
                <p class="attraction-card__desc">${linkifyUrlsInPlainText(prepareAttractionDescription(a.description, gmRaw))}</p>
                ${linksRow}
                ${credit}
                ${pHtml ? `<dl class="attraction-card__facts">${pHtml}</dl>` : ''}
              </div>
            </label>`;
          }).join('')}
        </div>
      </div>`;
    root.querySelectorAll('.attr-pick').forEach((cb) => {
      cb.addEventListener('change', () => {
        state.selectedAttractionIds = Array.from(root.querySelectorAll('.attr-pick:checked')).map(x => x.value);
        updateItineraryNextButton();
        saveItineraryDraft();
      });
    });
    root.querySelector('#btn-select-all-attrs')?.addEventListener('click', () => {
      const cbs = Array.from(root.querySelectorAll('.attr-pick'));
      const allChecked = cbs.every(cb => cb.checked);
      cbs.forEach(cb => cb.checked = !allChecked);
      state.selectedAttractionIds = Array.from(root.querySelectorAll('.attr-pick:checked')).map(x => x.value);
      updateItineraryNextButton();
      saveItineraryDraft();
    });
    state.selectedAttractionIds = Array.from(root.querySelectorAll('.attr-pick:checked')).map(x => x.value);
    updateItineraryNextButton();
    saveItineraryDraft();
    return;
  }
  if (step === 'select_meals') {
    state.itineraryWorkflowStep = 'meals';
    const rb = data;
    const dates = rb.trip_dates || [];
    const rp = rb.route_plan || {};
    const neigh = rb.neighborhoods || [];
    const legs = rp.transit_legs || [];
    const daily = rp.daily_schedule || [];
    const lodging = rp.lodging_strategy || '';
    let html = `<div class="itinerary-phase"><h3>동선·추천 동네</h3>`;
    if (lodging) html += `<p>${escapeHtml(lodging)}</p>`;
    if (legs.length) {
      html += '<h4>공항 이동 구간</h4><ul>';
      legs.forEach((leg) => {
        html += `<li><strong>${escapeHtml(leg.leg || '')}</strong>: ${escapeHtml(leg.notes || '')}`;
        if (leg.suggested_overnight) html += ` (숙박 제안: ${escapeHtml(leg.suggested_overnight)})`;
        html += '</li>';
      });
      html += '</ul>';
    }
    if (neigh.length) {
      html += '<h4>숙소 후보 동네</h4>';
      neigh.forEach((n) => {
        html += `<div class="option-item" style="margin-bottom:0.75rem;">
          <strong>${escapeHtml(n.name || '')}</strong> <span class="muted">${escapeHtml(n.area_id || '')}</span>
          <p class="muted">${escapeHtml(n.description || '')}</p>
          <p class="muted">${escapeHtml(n.lodging_notes || '')}</p>
        </div>`;
      });
    }
    if (daily.length) {
      html += '<h4>일자별 명소 배정 (구글맵 도로·체류 시간 반영)</h4><ul>';
      daily.forEach((row) => {
        const extra = Array.isArray(row.extra_attraction_ids) && row.extra_attraction_ids.length
          ? ` · 추가 ${escapeHtml(row.extra_attraction_ids.join(', '))}` : '';
        const warn = row.schedule_pace_warning ? ` <span class="muted">(${escapeHtml(row.schedule_pace_warning)})</span>` : '';
        const notes = row.route_notes ? `<div class="muted" style="font-size:0.88rem;margin:0.25rem 0 0;">${escapeHtml(row.route_notes)}</div>` : '';
        html += `<li><strong>${escapeHtml(row.date || '')}</strong>: 오전 ${escapeHtml(row.morning_attraction_id || '—')} · 오후 ${escapeHtml(row.afternoon_attraction_id || '—')}${extra} · ${escapeHtml(row.overnight_area_hint || '')}${warn}${notes}</li>`;
      });
      html += '</ul>';
    }
    html += '<h3>맛집 (명소당 3곳, 평점순) — 날짜별 점심·저녁 1·2순위</h3>';
    const mealOptsHtml = (opts, selectedId) =>
      opts.map((o) =>
        `<option value="${escapeHtml(o.id)}"${o.id === selectedId ? ' selected' : ''}>${escapeHtml(o.name || '')} (${Number(o.rating).toFixed(1)})</option>`
      ).join('');
    dates.forEach((d) => {
      const opts = getRestaurantOptionsForDay(rb, d);
      const mc = state.mealChoices?.[d] || {};
      if (!opts.length) {
        html += `<p class="muted">${escapeHtml(d)}: 해당 날짜 맛집 후보가 없습니다.</p>`;
        return;
      }
      html += `<div class="option-item" style="margin-bottom:1rem;"><h4>${escapeHtml(d)}</h4>
        <p class="muted">점심 (당일 방문 명소 인근)</p>
        <div style="display:flex; flex-wrap:wrap; gap:0.5rem; align-items:center;">
          <span>1순위</span><select data-date="${escapeHtml(d)}" data-meal="lunch" data-rank="first" style="min-width:14rem;">
            <option value="">선택</option>${mealOptsHtml(opts, mc.lunch?.first)}</select>
          <span>2순위</span><select data-date="${escapeHtml(d)}" data-meal="lunch" data-rank="second" style="min-width:14rem;">
            <option value="">선택</option>${mealOptsHtml(opts, mc.lunch?.second)}</select>
        </div>
        <p class="muted">저녁</p>
        <div style="display:flex; flex-wrap:wrap; gap:0.5rem; align-items:center;">
          <span>1순위</span><select data-date="${escapeHtml(d)}" data-meal="dinner" data-rank="first" style="min-width:14rem;">
            <option value="">선택</option>${mealOptsHtml(opts, mc.dinner?.first)}</select>
          <span>2순위</span><select data-date="${escapeHtml(d)}" data-meal="dinner" data-rank="second" style="min-width:14rem;">
            <option value="">선택</option>${mealOptsHtml(opts, mc.dinner?.second)}</select>
        </div></div>`;
    });
    html += '</div>';
    root.innerHTML = html;
    root.addEventListener('change', () => {
      snapshotMealChoicesFromDom();
      saveItineraryDraft();
    });
    updateItineraryNextButton();
    saveItineraryDraft();
    return;
  }
  if (step === 'complete') {
    state.itineraryWorkflowStep = 'complete';
    const fi = data.final_itinerary || {};
    root.innerHTML = `<div class="itinerary-phase">
      <h3>${escapeHtml(fi.title || '확정 일정')}</h3>
      <p>${escapeHtml(fi.summary || '')}</p>
      <h4>일자별 요약</h4>
      <pre style="white-space:pre-wrap; font-size:0.85rem;">${escapeHtml(JSON.stringify(fi.daily_plan || fi, null, 2))}</pre>
    </div>`;
    updateItineraryNextButton();
    saveItineraryDraft();
    return;
  }
  if (state.itineraries?.length) {
    renderItineraries(state.itineraries);
  }
}

function applyItineraryResponse(data) {
  if (data?.error) throw new Error(data.error);
  if (data?.itinerary_step === 'select_attractions') {
    const prevCatalog = state.itineraryAttractionCatalog;
    const prevSelected = [...(state.selectedAttractionIds || [])];
    state.itineraryAttractionCatalog = data.attractions || [];
    state.itineraryTripDays = data.trip_days != null ? data.trip_days : null;
    sanitizeAttractionCatalogInPlace(state.itineraryAttractionCatalog);
    state.selectedAttractionIds = reconcileAttractionIdsAfterCatalogUpdate(
      prevCatalog,
      prevSelected,
      state.itineraryAttractionCatalog,
    );
    state.itineraryRouteBundle = null;
    state.mealChoices = {};
    state.selectedItinerary = null;
    state.itineraries = [];
    state.itineraryWorkflowStep = 'attractions';
    renderItineraryWorkflow(data);
    mountItineraryStepPanel('attractions');
    show('step-attractions');
    saveItineraryDraft();
    return true;
  }
  if (data?.itinerary_step === 'select_meals') {
    state.itineraryRouteBundle = data;
    state.selectedItinerary = null;
    state.itineraryWorkflowStep = 'meals';
    renderItineraryWorkflow(data);
    mountItineraryStepPanel('plan');
    show('step-itinerary-plan');
    saveItineraryDraft();
    return true;
  }
  if (data?.itinerary_step === 'complete') {
    state.selectedItinerary = data.final_itinerary;
    state.itineraryWorkflowStep = 'complete';
    renderItineraryWorkflow(data);
    mountItineraryStepPanel('plan');
    show('step-itinerary-plan');
    saveItineraryDraft();
    return true;
  }
  let itin = Array.isArray(data) ? data : (data?.itineraries || data);
  if (!Array.isArray(itin)) itin = [itin];
  state.itineraries = itin;
  state.itineraryWorkflowStep = 'legacy';
  state.selectedItinerary = null;
  mountItineraryStepPanel('plan');
  renderItineraries(state.itineraries);
  show('step-itinerary-plan');
  saveItineraryDraft();
  return true;
}

function renderItineraries(items) {
  const list = $('#itinerary-workflow-root');
  if (!list) return;
  state.itineraryWorkflowStep = 'legacy';
  list.innerHTML = items.map((it, i) => `
    <div class="option-item" data-idx="${i}">
      <h3>${escapeHtml(it.title || `일정 ${i + 1}`)}</h3>
      <p>${escapeHtml(it.summary || '')}</p>
    </div>
  `).join('');
  list.querySelectorAll('.option-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.selectedItinerary = items[parseInt(el.dataset.idx, 10)];
      updateItineraryNextButton();
      saveItineraryDraft();
    });
  });
  updateItineraryNextButton();
}

$('#btn-back-rental').addEventListener('click', () => {
  if (state.flightSkipped) show('step-rental-decide');
  else show('step-flights');
});

const btnRentalRefresh = $('#btn-rental-refresh');
if (btnRentalRefresh) btnRentalRefresh.addEventListener('click', async () => {
  if (state.travelInput?.local_transport !== 'rental_car') return;
  if (!state.flightSkipped && !buildSelectedFlight()) {
    alert('항공편을 먼저 선택해 주세요.');
    return;
  }
  state.travelInput = buildTravelInput();
  const pickupDt = $('#rental-pickup-dt')?.value;
  const dropoffDt = $('#rental-dropoff-dt')?.value;
  const pickupIata = ($('#rental-pickup-iata')?.value || '').trim().toUpperCase().slice(0, 3);
  if (!pickupDt || !dropoffDt) {
    alert('픽업·반납 일시를 입력해 주세요.');
    return;
  }
  show('loading');
  try {
    const payload = {
      ...baseSessionPayload(),
      selected_flight: state.flightSkipped ? null : buildSelectedFlight(),
      rental_search: {
        pickup_datetime: pickupDt,
        dropoff_datetime: dropoffDt,
        pickup_iata: pickupIata.length === 3 ? pickupIata : undefined,
      },
    };
    const data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    if (data?.step !== 'rental') throw new Error('렌트카 검색 응답이 올바르지 않습니다.');
    state.localTransport = normalizeLocalTransport(data?.local_transport);
    state.selectedLocalTransport = null;
    renderRentalOptions(state.localTransport);
    show('step-rental');
    fillRentalSearchFormFromFlight(false);
  } catch (err) {
    showError(err.message);
  }
});

function showItineraryDecide() {
  show('step-itinerary-decide');
}

async function proceedFromRentalToItinerary() {
  state.rentalSkipped = false;
  const ltNorm = normalizeLocalTransport(state.localTransport);
  if (state.travelInput?.local_transport === 'rental_car' && ltNorm.length === 0) {
    alert('렌트카 검색 결과가 없습니다. 픽업·반납 일시와 공항 코드를 확인한 뒤 「이 일정으로 다시 검색」을 눌러 주세요.');
    return;
  }
  state.selectedLocalTransport = state.selectedLocalTransport || ltNorm[0] || {};
  show('loading');
  try {
    const payload = baseSessionPayload({
      selected_flight: state.selectedFlight,
      selected_local_transport: state.selectedLocalTransport,
    });
    const data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    applyItineraryResponse(data);
  } catch (err) {
    showAgentError(err.message);
  }
}

$('#btn-next-rental').addEventListener('click', () => {
  showItineraryDecide();
});

$('#btn-itinerary-decide-go')?.addEventListener('click', () => proceedFromRentalToItinerary());
$('#btn-itinerary-decide-skip')?.addEventListener('click', () => skipItineraryToAccommodation());
$('#btn-back-itinerary-decide')?.addEventListener('click', () => show('step-rental'));

$('#btn-back-itineraries').addEventListener('click', () => {
  const ws = state.itineraryWorkflowStep;
  if (ws === 'legacy') {
    show('step-rental');
    return;
  }
  if (ws === 'meals' || ws === 'complete') {
    state.itineraryWorkflowStep = 'attractions';
    state.itineraryRouteBundle = null;
    state.mealChoices = {};
    saveItineraryDraft();
    mountItineraryStepPanel('attractions');
    show('step-attractions', true);
    refreshStepView('attractions');
    return;
  }
  show('step-rental');
});

async function skipRentalToItinerary() {
  state.rentalSkipped = true;
  show('loading');
  try {
    const data = await callAgent(baseSessionPayload({ selected_flight: state.selectedFlight }));
    if (data?.error) throw new Error(data.error);
    applyItineraryResponse(data);
  } catch (err) {
    showAgentError(err.message);
  }
}

async function skipItineraryToAccommodation() {
  const dest = state.travelInput?.destination || '';
  const stub = {
    title: '일정 단계를 건너뛰었습니다',
    summary: `${dest} — 명소·동선·맛집 없이 숙소 검색으로 이동합니다.`,
    route_plan: { daily_schedule: [] },
    skipped: true,
  };
  state.selectedItinerary = stub;
  show('loading');
  try {
    const data = await callAgent(baseSessionPayload({
      selected_flight: state.selectedFlight,
      selected_itinerary: stub,
    }));
    if (data?.error) throw new Error(data.error);
    const acc = data?.accommodations || [];
    const lt = data?.local_transport || [];
    state.accommodations = Array.isArray(acc) ? acc : [];
    state.localTransport = normalizeLocalTransport(lt);
    renderAccommodations(state.accommodations);
    $('#local-transport-info').innerHTML = state.localTransport.length
      ? `<h4>현지 이동</h4><pre>${JSON.stringify(state.localTransport, null, 2)}</pre>`
      : '';
    show('step-accommodation');
  } catch (err) {
    showError(err.message);
  }
}

async function skipAccommodationToConfirm() {
  state.selectedAccommodation = {
    id: 'skipped',
    name: '숙소 선택 건너뛰기',
    location: '',
    skipped: true,
  };
  show('loading');
  try {
    const data = await callAgent(baseSessionPayload({
      selected_flight: state.selectedFlight,
      selected_itinerary: state.selectedItinerary,
      selected_accommodation: state.selectedAccommodation,
    }));
    if (data?.error) throw new Error(data.error);
    $('#booking-guidance').innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    show('step-confirm');
  } catch (err) {
    showError(err.message);
  }
}

function showAccommodationDecide() {
  show('step-accommodation-decide');
}

async function proceedFromItineraryCompleteToAccommodation() {
  if (!state.selectedItinerary) {
    alert('일정이 없습니다.');
    return;
  }
  show('loading');
  try {
    const payload = baseSessionPayload({
      selected_flight: state.selectedFlight,
      selected_itinerary: state.selectedItinerary,
    });
    const data = await callAgent(payload);
    if (data?.error) throw new Error(data.error);
    const acc = data?.accommodations || [];
    const lt = data?.local_transport || [];
    state.accommodations = Array.isArray(acc) ? acc : [];
    state.localTransport = normalizeLocalTransport(lt);
    renderAccommodations(state.accommodations);
    $('#local-transport-info').innerHTML = state.localTransport.length
      ? `<h4>현지 이동</h4><pre>${JSON.stringify(state.localTransport, null, 2)}</pre>`
      : '';
    show('step-accommodation');
  } catch (err) {
    showError(err.message);
  }
}

$('#btn-accommodation-decide-go')?.addEventListener('click', () => proceedFromItineraryCompleteToAccommodation());
$('#btn-accommodation-decide-skip')?.addEventListener('click', () => skipAccommodationToConfirm());
$('#btn-back-accommodation-decide')?.addEventListener('click', () => {
  goToItinerarySectionForState();
  const st = state.itineraryWorkflowStep === 'attractions' ? 'attractions' : 'itinerary';
  refreshStepView(st);
});

$('#btn-next-itineraries').addEventListener('click', async () => {
  const ws = state.itineraryWorkflowStep;
  if (ws === 'attractions') {
    if (!state.selectedAttractionIds?.length) {
      alert('명소를 한 곳 이상 선택해 주세요.');
      return;
    }
    show('loading');
    try {
      const payload = baseSessionPayload({
        selected_flight: state.selectedFlight,
        selected_local_transport: state.selectedLocalTransport,
        itinerary_phase: 'route_restaurants',
        selected_attraction_ids: state.selectedAttractionIds,
        itinerary_attraction_catalog: state.itineraryAttractionCatalog,
      });
      const data = await callAgent(payload);
      if (data?.error) throw new Error(data.error);
      applyItineraryResponse(data);
    } catch (err) {
      showAgentError(err.message);
    }
    return;
  }
  if (ws === 'meals') {
    if (!collectAndValidateMealChoices()) return;
    show('loading');
    try {
      const payload = baseSessionPayload({
        selected_flight: state.selectedFlight,
        selected_local_transport: state.selectedLocalTransport,
        itinerary_phase: 'finalize',
        meal_choices: state.mealChoices,
        route_plan_bundle: state.itineraryRouteBundle,
      });
      const data = await callAgent(payload);
      if (data?.error) throw new Error(data.error);
      applyItineraryResponse(data);
    } catch (err) {
      showAgentError(err.message);
    }
    return;
  }
  if (ws === 'complete') {
    if (!state.selectedItinerary) {
      alert('일정이 없습니다.');
      return;
    }
    showAccommodationDecide();
    return;
  }
  if (ws === 'legacy') {
    if (!state.selectedItinerary) {
      alert('일정을 선택해 주세요.');
      return;
    }
    showAccommodationDecide();
    return;
  }
  alert('일정 단계를 진행해 주세요.');
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

$('#btn-back-accommodation').addEventListener('click', () => {
  goToItinerarySectionForState();
  const st = state.itineraryWorkflowStep === 'attractions' ? 'attractions' : 'itinerary';
  refreshStepView(st);
});

$('#btn-confirm-booking').addEventListener('click', async () => {
  if (!state.selectedAccommodation) { alert('숙소를 선택해 주세요.'); return; }
  show('loading');
  try {
    const payload = baseSessionPayload({
      selected_flight: state.selectedFlight,
      selected_itinerary: state.selectedItinerary,
      selected_accommodation: state.selectedAccommodation,
    });
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

/** 왕복/단일 구간의 목적지 도시명(멀티시티는 마지막 구간 목적지) */
function getPrimaryDestinationTextForAirportValidation() {
  const form = $('#travel-form');
  if (!form) return '';
  const type = form.trip_type?.value;
  if (type === 'multi_city' && state.multi_cities?.length) {
    const last = state.multi_cities[state.multi_cities.length - 1];
    return (last?.destination || '').trim();
  }
  return (form.destination?.value || '').trim();
}

function getPrimaryOriginTextForAirportValidation() {
  const form = $('#travel-form');
  if (!form) return '';
  const type = form.trip_type?.value;
  if (type === 'multi_city' && state.multi_cities?.length) {
    return (state.multi_cities[0].origin || '').trim();
  }
  return (form.origin?.value || '').trim();
}

/**
 * 목적지 문자열과 맞지 않는 destination_airport_code만 제거(이전 여행 MXP 등).
 * 목적지와 일치하는 저장값(FTE 등)은 유지한다.
 */
function validateDestinationAirportMatchesDestination() {
  const dest = getPrimaryDestinationTextForAirportValidation();
  if (!dest || (typeof isAirportCode === 'function' && isAirportCode(dest))) return;
  const code = state.destination_airport_code;
  if (!code) return;
  const airports = typeof getAirportsForCity === 'function' ? getAirportsForCity(dest) : null;
  if (!airports || !airports.length) {
    state.destination_airport_code = null;
    return;
  }
  const ok = airports.some((a) => a.code === code);
  if (!ok) state.destination_airport_code = null;
}

/**
 * 등록 도시인데 공항 미선택이면 출발지·마일리지 규칙으로 정렬된 목록의 첫 공항을 기본값으로 설정(검색 가능하게).
 */
function applyDefaultDestinationAirportIfMissing() {
  const form = $('#travel-form');
  if (!form) return;
  const dest = getPrimaryDestinationTextForAirportValidation();
  if (!dest || (typeof isAirportCode === 'function' && isAirportCode(dest))) return;
  if (state.destination_airport_code) return;
  if (typeof getAirportsForCity !== 'function' || !getAirportsForCity(dest)?.length) return;
  const origin = getPrimaryOriginTextForAirportValidation();
  const originCode = state.origin_airport_code || origin || '';
  const routeContext = {
    originInput: origin,
    destInput: dest,
    originAirportCode: state.origin_airport_code,
    destAirportCode: null,
    domesticRoute: typeof isDomesticRoute === 'function' && isDomesticRoute(
      origin,
      dest,
      state.origin_airport_code,
      null,
    ),
  };
  const options = {
    useMiles: form.use_miles?.checked ?? false,
    mileageProgram: form.mileage_program?.value?.trim() || '',
    routeContext,
  };
  let list = typeof getDestAirportsForOrigin === 'function'
    ? getDestAirportsForOrigin(originCode, dest, options)
    : null;
  if (!list || !list.length) {
    list = typeof getAirportsForPlaceWithGroundRules === 'function'
      ? getAirportsForPlaceWithGroundRules(dest, 'destination', { routeContext })
      : (typeof getAirportsForCity === 'function' ? getAirportsForCity(dest) : null);
  }
  if (Array.isArray(list) && list.length && list[0]?.code) {
    state.destination_airport_code = list[0].code;
  }
}

function initDestinationAirportSync() {
  const el = $('#destination_input');
  if (!el) return;
  let last = (el.value || '').trim();
  el.addEventListener('input', () => {
    const v = (el.value || '').trim();
    if (v !== last) {
      state.destination_airport_code = null;
      last = v;
      try {
        saveFormToStorage();
      } catch (_) { /* ignore */ }
    }
  });
  el.addEventListener('blur', () => {
    validateDestinationAirportMatchesDestination();
    applyDefaultDestinationAirportIfMissing();
    try {
      saveFormToStorage();
    } catch (_) { /* ignore */ }
  });
}

function initStepIndicator() {
  loadFormFromStorage();
  syncTravelInputFromForm();
  restoreItineraryDraft();
  show('step-input');
  validateDestinationAirportMatchesDestination();
  applyDefaultDestinationAirportIfMissing();
  initDestinationAirportSync();
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
  const skipFlightsBtn = $('#btn-travel-skip-flights');
  const skipHint = $('#travel-skip-flights-hint');
  if (skipFlightsBtn && skipHint) {
    if (val === 'multi_city') {
      skipFlightsBtn.style.display = 'none';
      skipHint.style.display = '';
    } else {
      skipFlightsBtn.style.display = '';
      skipHint.style.display = 'none';
    }
  }

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
  const btnExport = $('#btn-export-plan');
  const btnImport = $('#btn-import-plan');
  const fileImportInput = $('#file-import-input');

  if (btnNew) btnNew.addEventListener('click', onNewPlanClick);
  if (btnSave) btnSave.addEventListener('click', onSavePlanClick);
  if (btnSaveAs) btnSaveAs.addEventListener('click', onSaveAsPlanClick);
  if (btnOpen) btnOpen.addEventListener('click', onOpenPlanClick);
  
  if (btnExport) btnExport.addEventListener('click', exportPlanToFile);
  if (btnImport && fileImportInput) {
    btnImport.addEventListener('click', () => fileImportInput.click());
    fileImportInput.addEventListener('change', importPlanFromFile);
  }

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
  const hasItineraryProgress = (state.itineraryAttractionCatalog?.length > 0)
    || state.itineraryRouteBundle
    || (state.selectedAttractionIds?.length > 0);
  if (state.currentPlanId || state.travelInput || state.flights?.length || state.itineraries?.length || hasItineraryProgress) {
    if (!confirm('현재 진행 중인 내용이 저장되지 않을 수 있습니다. 새 계획을 만드시겠습니까?')) return;
  }
  newPlan();
}
async function onSavePlanClick() {
  const ok = await savePlan();
  if (ok) {
    saveItineraryDraft();
    alert('저장되었습니다.');
    renderPlanUI();
  } else {
    alert('저장할 내용이 없거나 이름 입력이 취소되었습니다.');
  }
}
async function onSaveAsPlanClick() {
  const ok = await savePlan(null, true);
  if (ok) {
    saveItineraryDraft();
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

async function exportPlanToFile() {
  try {
    const planState = getFullPlanState();
    const planName = state.currentPlanName || getDefaultPlanName();
    const dataStr = JSON.stringify({ name: planName, data: planState }, null, 2);
    const fileName = `${planName}.json`;

    // 최신 브라우저(크롬/엣지)의 경우 '다른 이름으로 저장' 다이얼로그 강제 호출
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: fileName,
          types: [{
            description: '여행 계획 파일 (.json)',
            accept: { 'application/json': ['.json'] },
          }],
        });
        const writable = await handle.createWritable();
        await writable.write(dataStr);
        await writable.close();
        alert(`저장 완료: ${fileName} 파일이 선택하신 위치에 안전하게 저장되었습니다!`);
        return;
      } catch (e) {
        // 사용자가 취소(Cancel)를 누른 경우
        if (e.name === 'AbortError') return; 
        console.warn('showSaveFilePicker failed, falling back to basic download:', e);
      }
    }

    // 구형 브라우저 또는 파일 픽커를 지원하지 않는 경우 (기본 다운로드 동작)
    const blob = new Blob([dataStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 0);
    
    alert(`파일이 브라우저의 기본 [다운로드] 폴더에 '${fileName}' 이름으로 저장되었습니다.\n(브라우저 우측 상단이나 하단의 다운로드 내역을 확인해 주세요)`);
  } catch (err) {
    console.error(err);
    alert('파일 내보내기에 실패했습니다.');
  }
}

function importPlanFromFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const content = e.target.result;
      const plan = JSON.parse(content);
      if (!plan || !plan.data) {
        alert('올바른 계획 파일(.json)이 아닙니다.');
        return;
      }
      loadPlanIntoState(plan.data);
      state.currentPlanId = null;
      state.currentPlanName = plan.name || '불러온 계획';
      saveFormToStorage();
      renderPlanUI();
      const step = resolveCurrentStep();
      const sectionId = STEP_TO_SECTION[step] || 'step-input';
      show(sectionId, true);
    } catch (err) {
      console.error(err);
      alert('파일을 읽는 중 오류가 발생했습니다.');
    } finally {
      event.target.value = '';
    }
  };
  reader.readAsText(file);
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
