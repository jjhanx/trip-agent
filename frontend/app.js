/* Trip Agent - Web UI */

const API_BASE = window.location.origin + '/a2a';
let state = {
  travelInput: null,
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

function show(id) {
  $$('section').forEach(s => s.classList.add('hidden'));
  const el = $(`#${id}`);
  if (el) el.classList.remove('hidden');
}

function showError(msg) {
  $('#error-message').textContent = msg;
  show('error');
}

async function callAgent(payload) {
  const resp = await fetch(API_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  return {
    origin: form.origin.value,
    destination: form.destination.value,
    start_date: form.start_date.value,
    end_date: form.end_date.value,
    start_time_preference: form.start_time_preference.value || null,
    local_transport: form.local_transport.value,
    accommodation_type: form.accommodation_type.value,
    seat_class: form.seat_class.value,
    use_miles: form.use_miles.checked,
    mileage_balance: parseInt(form.mileage_balance.value) || 0,
    mileage_program: form.mileage_program.value || null,
    preference: {
      pace: form.pace.value,
      budget_level: form.budget_level.value,
    },
  };
}

$('#travel-form').addEventListener('submit', async (e) => {
  e.preventDefault();
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

$('#btn-back-flights').addEventListener('click', () => show('step-input'));

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
