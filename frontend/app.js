/* Trip Agent - Web UI */

const API_BASE = window.location.origin + '/a2a/';
const STORAGE_KEY = 'trip-agent-form';

function loadFormFromStorage() {
  try {
    const s = localStorage.getItem(STORAGE_KEY);
    if (!s) return;
    const data = JSON.parse(s);
    const form = $('#travel-form');
    if (!form) return;
    const set = (name, v) => { const el = form[name]; if (el && v != null) el.value = String(v); };
    const setCheck = (name, v) => { const el = form[name]; if (el) el.checked = !!v; };
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
  } catch (_) { /* ignore */ }
}

function saveFormToStorage() {
  try {
    const form = $('#travel-form');
    if (!form) return;
    const data = {
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
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (_) { /* ignore */ }
}
let state = {
  travelInput: null,
  origin_airport_code: null,
  destination_airport_code: null,
  flights: [],
  selectedFlight: null,
  itineraries: [],
  selectedItinerary: null,
  accommodations: [],
  selectedAccommodation: null,
  localTransport: [],
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

const STEP_IDS = {
  'step-input': 'input',
  'step-origin-airports': 'input',
  'step-destination-airports': 'input',
  'step-flights': 'flights',
  'step-itineraries': 'itineraries',
  'step-accommodation': 'accommodation',
  'step-confirm': 'booking',
};

function show(id) {
  $$('section').forEach(s => s.classList.add('hidden'));
  const el = $(`#${id}`);
  if (el) el.classList.remove('hidden');
  const step = STEP_IDS[id];
  if (step) {
    $$('#step-indicator .step-node').forEach(node => {
      node.classList.toggle('active', node.dataset.step === step);
    });
  }
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

  const flex = parseInt(form.date_flexibility_days?.value, 10);
  const male = parseInt(form.travelers_male?.value, 10) || 0;
  const female = parseInt(form.travelers_female?.value, 10) || 0;
  const children = parseInt(form.travelers_children?.value, 10) || 0;
  const input = {
    origin: form.origin.value,
    destination: form.destination.value,
    start_date: form.start_date.value,
    end_date: form.end_date.value,
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
  return input;
}

function needOriginAirport() {
  const origin = $('#travel-form').origin?.value?.trim() || '';
  return origin && !isAirportCode(origin) && getAirportsForCity(origin);
}

function needDestAirport() {
  const dest = $('#travel-form').destination?.value?.trim() || '';
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
  list.innerHTML = airports.map(a => {
    const fa = info[a.code] || {};
    const badges = [];
    if (fa.direct) badges.push('<span class="airport-badge direct">직항</span>');
    if (options.useMiles && mileageKey && fa.mileage?.includes(mileageKey)) badges.push('<span class="airport-badge mileage">마일리지</span>');
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

async function doFlightSearch() {
  state.travelInput = buildTravelInput();
  show('loading');
  try {
    let data = await callAgent(state.travelInput);
    if (data?.error) throw new Error(data.error);
    let flights = Array.isArray(data) ? data : (data?.flights || []);
    if (!Array.isArray(flights) && typeof data === 'object' && !data.step) {
      flights = [data];
    }
    const warnings = data?.warnings || [];
    state.flights = flights;
    renderFlights(flights, warnings);
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
  const warns = warnings || [];
  const isMock = warns.some(w => /mock/i.test(String(w))) ||
    (Array.isArray(flights) && flights.some(f => f?.source === 'mock'));

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
  list.innerHTML = (flights || []).map((f, i) => {
    const route = `${f.origin || ''} → ${f.destination || ''}`;
    const timeRange = `${fmtFlightDateTime(f.departure)} ~ ${fmtFlightDateTime(f.arrival)}`;
    const duration = f.duration_hours ? ` · 약 ${f.duration_hours}시간` : '';
    const price = f.price_krw ? f.price_krw.toLocaleString() + '원' : (f.miles_required || 0) + '마일';
    return `
    <div class="option-item" data-idx="${i}">
      <h3>${f.airline || '항공사'} ${f.flight_number || ''}</h3>
      <p class="flight-route">${route}</p>
      <p class="flight-time">${timeRange}${duration}</p>
      <p class="price">${price}</p>
    </div>
  `;
  }).join('');
  list.querySelectorAll('.option-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.option-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.selectedFlight = flights[parseInt(el.dataset.idx)];
    });
  });
}

$('#btn-back-flights').addEventListener('click', () => {
  state.origin_airport_code = null;
  state.destination_airport_code = null;
  show('step-input');
});

$('#btn-next-flights').addEventListener('click', async () => {
  if (!state.selectedFlight) { alert('항공편을 선택해 주세요.'); return; }
  show('loading');
  try {
    const payload = { ...state.travelInput, selected_flight: state.selectedFlight };
    let data = await callAgent(payload);
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

$('#btn-back-itineraries').addEventListener('click', () => show('step-flights'));

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
  const selectedStart = startInput ? new Date(startInput + 'T12:00:00') : null;
  const selectedEnd = endInput ? new Date(endInput + 'T12:00:00') : null;

  let html = '';
  for (let i = 0; i < startDay; i++) {
    const d = new Date(year, month, -startDay + i + 1);
    const ymd = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    html += `<span class="other-month" data-date="${ymd}">${d.getDate()}</span>`;
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, month, d);
    const ymd = `${year}-${String(month + 1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    let cls = '';
    if (selectedStart && date.getTime() === selectedStart.getTime()) cls = 'selected';
    if (selectedEnd && date.getTime() === selectedEnd.getTime()) cls = 'selected';
    html += `<span data-date="${ymd}" ${cls ? `class="${cls}"` : ''}>${d}</span>`;
  }
  const totalCells = startDay + daysInMonth;
  const remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
  for (let i = 0; i < remaining; i++) {
    const nextDate = new Date(year, month + 1, i + 1);
    const ymd = `${nextDate.getFullYear()}-${String(nextDate.getMonth()+1).padStart(2,'0')}-${String(nextDate.getDate()).padStart(2,'0')}`;
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
      if (calendarTarget === 'start') {
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
  const input = target === 'start' ? $('#start_date_input') : $('#end_date_input');
  let val = input?.value;
  if (target === 'end' && !val) {
    const startVal = $('#start_date_input')?.value;
    if (startVal) val = startVal;
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
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initStepIndicator);
} else {
  initStepIndicator();
}

$('#travel-form')?.addEventListener('input', saveFormToStorage);
$('#travel-form')?.addEventListener('change', saveFormToStorage);

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
