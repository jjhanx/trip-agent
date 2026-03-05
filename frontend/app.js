/* Trip Agent - Web UI */

const API_BASE = window.location.origin + '/a2a/';
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
  const msg = data.result?.message?.parts?.[0]?.text;
  if (!msg) throw new Error('No response');
  try {
    return JSON.parse(msg);
  } catch {
    return { raw: msg };
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
    });
  });
}

function renderDestAirports() {
  const dest = $('#travel-form').destination?.value?.trim() || '';
  const originCode = state.origin_airport_code || $('#travel-form').origin?.value?.trim() || '';
  const airports = getDestAirportsForOrigin(originCode, dest) || getAirportsForCity(dest) || [];
  const list = $('#destination-airports-list');
  list.innerHTML = airports.map(a => `
    <div class="airport-item" data-code="${a.code}">
      <span><span class="code">${a.code}</span> <span class="name">${a.name}</span></span>
    </div>
  `).join('');
  list.querySelectorAll('.airport-item').forEach(el => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.airport-item').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      state.destination_airport_code = el.dataset.code;
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
    state.flights = flights;
    renderFlights(flights);
    show('step-flights');
  } catch (err) {
    showError(err.message);
  }
}

$('#travel-form').addEventListener('submit', async (e) => {
  e.preventDefault();

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

function renderFlights(flights) {
  const list = $('#flights-list');
  list.innerHTML = flights.map((f, i) => `
    <div class="option-item" data-idx="${i}">
      <h3>${f.airline || '항공사'} ${f.flight_number || ''}</h3>
      <p>${f.departure || ''} - ${f.arrival || ''}</p>
      <p class="price">${f.price_krw ? f.price_krw.toLocaleString() + '원' : (f.miles_required || 0) + '마일'}</p>
    </div>
  `).join('');
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
  $('#calendar-days').querySelectorAll('span[data-date]').forEach(span => {
    span.addEventListener('click', () => {
      const ymd = span.dataset.date;
      if (!ymd) return;
      if (calendarTarget === 'start') {
        $('#start_date_input').value = ymd;
      } else if (calendarTarget === 'end') {
        $('#end_date_input').value = ymd;
      }
      calendarTarget = null;
      $('#calendar-picker').classList.add('hidden');
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

function initStepIndicator() { show('step-input'); }
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initStepIndicator);
} else {
  initStepIndicator();
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
