/**
 * 도시/관광지 → 접근 가능 공항 (차량 이동 시간·국가 메타 포함)
 * 국제선: 목적지 기준 차로 8시간 이내, 같은 나라 공항 우선 후 거리순.
 * 국내선: 차로 3시간 이상 거리의 공항 우선(후보 없으면 8시간 이내로 완화).
 */
const CITY_AIRPORTS = {
  서울: [
    { code: 'ICN', name: '인천국제공항', drive_hours: 1, country: 'KR' },
    { code: 'GMP', name: '김포국제공항', drive_hours: 0.5, country: 'KR' },
  ],
  인천: [
    { code: 'ICN', name: '인천국제공항', drive_hours: 0.5, country: 'KR' },
    { code: 'GMP', name: '김포국제공항', drive_hours: 1, country: 'KR' },
  ],
  부산: [
    { code: 'PUS', name: '김해국제공항', drive_hours: 0.5, country: 'KR' },
    { code: 'GMP', name: '김포국제공항', drive_hours: 4, country: 'KR' },
    { code: 'ICN', name: '인천국제공항', drive_hours: 4.5, country: 'KR' },
  ],
  제주: [{ code: 'CJU', name: '제주국제공항', drive_hours: 0.3, country: 'KR' }],
  오사카: [
    { code: 'KIX', name: '간사이국제공항', drive_hours: 1, country: 'JP' },
    { code: 'ITM', name: '오사카(이타미)', drive_hours: 0.5, country: 'JP' },
  ],
  도쿄: [
    { code: 'NRT', name: '나리타국제공항', drive_hours: 1.5, country: 'JP' },
    { code: 'HND', name: '하네다공항', drive_hours: 0.5, country: 'JP' },
  ],
  방콕: [
    { code: 'BKK', name: '수완나품국제공항', drive_hours: 0.5, country: 'TH' },
    { code: 'DMK', name: '돈므앙공항', drive_hours: 1, country: 'TH' },
  ],
  싱가포르: [{ code: 'SIN', name: '창이공항', drive_hours: 0.5, country: 'SG' }],
  홍콩: [{ code: 'HKG', name: '홍콩국제공항', drive_hours: 0.5, country: 'HK' }],
  돌로미티: [
    { code: 'MXP', name: '밀라노 말펜사', drive_hours: 3.5, country: 'IT' },
    { code: 'VCE', name: '베니스 마르코폴로', drive_hours: 2, country: 'IT' },
    { code: 'VRN', name: '베로나', drive_hours: 2, country: 'IT' },
    { code: 'TSF', name: '베니스 트레비소', drive_hours: 2.5, country: 'IT' },
    { code: 'BZO', name: '볼차노', drive_hours: 1.5, country: 'IT' },
    { code: 'INN', name: '인스부르크', drive_hours: 2, country: 'AT' },
    { code: 'MUC', name: '뮌헨', drive_hours: 4, country: 'DE' },
  ],
  도로미티: [
    { code: 'MXP', name: '밀라노 말펜사', drive_hours: 3.5, country: 'IT' },
    { code: 'VCE', name: '베니스 마르코폴로', drive_hours: 2, country: 'IT' },
    { code: 'VRN', name: '베로나', drive_hours: 2, country: 'IT' },
    { code: 'TSF', name: '베니스 트레비소', drive_hours: 2.5, country: 'IT' },
    { code: 'BZO', name: '볼차노', drive_hours: 1.5, country: 'IT' },
    { code: 'INN', name: '인스부르크', drive_hours: 2, country: 'AT' },
    { code: 'MUC', name: '뮌헨', drive_hours: 4, country: 'DE' },
  ],
  /** 남미 파타고니아(아르헨티나·칠레) — 이탈리아 공항과 혼동되지 않게 별도 키 */
  /** drive_hours: 지역 중심(남부) 기준 대략적 접근성 — 정렬 시 ‘가까운’ 공항 우선(EZE·SCL은 허브) */
  파타고니아: [
    { code: 'FTE', name: '엘 칼라파테', drive_hours: 0.5, country: 'AR' },
    { code: 'USH', name: '우수아이아', drive_hours: 1, country: 'AR' },
    { code: 'PMC', name: '푸에르토 몬트', drive_hours: 2, country: 'CL' },
    { code: 'EZE', name: '부에노스아이레스 에세이사', drive_hours: 5, country: 'AR' },
    { code: 'SCL', name: '산티아고', drive_hours: 5, country: 'CL' },
  ],
  Patagonia: [
    { code: 'FTE', name: 'El Calafate', drive_hours: 0.5, country: 'AR' },
    { code: 'USH', name: 'Ushuaia', drive_hours: 1, country: 'AR' },
    { code: 'PMC', name: 'Puerto Montt', drive_hours: 2, country: 'CL' },
    { code: 'EZE', name: 'Buenos Aires Ezeiza', drive_hours: 5, country: 'AR' },
    { code: 'SCL', name: 'Santiago', drive_hours: 5, country: 'CL' },
  ],
};

/** 미국 서부 Grand Circle 등 — 여러 국립공원 묶음. 항공편은 출발 공항과의 대원거리로 가장 가까운 공항 우선 */
const _grandCircleAirports = [
  { code: 'LAX', name: '로스앤젤레스 LAX', drive_hours: 5, country: 'US' },
  { code: 'LAS', name: 'Harry Reid / 라스베이거스', drive_hours: 2.5, country: 'US' },
  { code: 'SLC', name: '솔트레이크시티', drive_hours: 3, country: 'US' },
  { code: 'PHX', name: '피닉스 스카이하버', drive_hours: 4, country: 'US' },
  { code: 'DEN', name: '덴버', drive_hours: 6, country: 'US' },
  { code: 'FLG', name: '플래그스태프 (그랜드 캐년 근접)', drive_hours: 1.5, country: 'US' },
];

CITY_AIRPORTS['Grand Circle'] = _grandCircleAirports;
CITY_AIRPORTS['그랜드 서클'] = _grandCircleAirports;

/** 도시 키 → 국가(ISO2). 공항 선택 시 앵커 국가로 사용 */
const CITY_COUNTRY = {
  서울: 'KR', 인천: 'KR', 부산: 'KR', 제주: 'KR',
  오사카: 'JP', 도쿄: 'JP', 방콕: 'TH', 싱가포르: 'SG', 홍콩: 'HK',
  돌로미티: 'IT', 도로미티: 'IT',
  파타고니아: 'AR', Patagonia: 'AR',
  'Grand Circle': 'US', '그랜드 서클': 'US',
};

/** IATA 공항 좌표(대원거리 비교). 지역 묶음(Grand Circle 등)일 때 출발 공항 기준 가장 가까운 도착 공항 우선 */
const AIRPORT_COORDS = {
  LAX: { lat: 33.942, lng: -118.408 },
  ICN: { lat: 37.469, lng: 126.451 },
  GMP: { lat: 37.558, lng: 126.791 },
  PUS: { lat: 35.179, lng: 129.075 },
  CJU: { lat: 33.506, lng: 126.493 },
  LAS: { lat: 36.084, lng: -115.153 },
  SLC: { lat: 40.789, lng: -111.979 },
  PHX: { lat: 33.434, lng: -112.013 },
  DEN: { lat: 39.856, lng: -104.674 },
  FLG: { lat: 35.138, lng: -111.671 },
};

const REGION_COLLECTION_KEYS = new Set(['Grand Circle', '그랜드 서클']);

function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const toR = (d) => (d * Math.PI) / 180;
  const dLat = toR(lat2 - lat1);
  const dLng = toR(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toR(lat1)) * Math.cos(toR(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Grand Circle 등 여러 국립공원 묶음 목적지인지 */
function isRegionCollectionDestination(destCityName) {
  const key = findCityKey(destCityName || '');
  return !!(key && REGION_COLLECTION_KEYS.has(key));
}

/**
 * 출발 공항 → 목적지 공항별 운항 정보
 * direct: 직항 여부, mileage: 해당 공항 직항이 있는 마일리지 프로그램
 */
const FLIGHT_INFO = {
  ICN: {
    KIX: { hours: 2, direct: true, mileage: ['skypass', 'asiana'] },
    NRT: { hours: 2, direct: true, mileage: ['skypass', 'asiana'] },
    HND: { hours: 2, direct: true, mileage: ['skypass', 'asiana'] },
    BKK: { hours: 5, direct: true, mileage: ['skypass', 'asiana'] },
    SIN: { hours: 6, direct: true, mileage: ['skypass', 'asiana'] },
    HKG: { hours: 4, direct: true, mileage: ['skypass', 'asiana'] },
    PUS: { hours: 1, direct: true, mileage: ['skypass', 'asiana'] },
    CJU: { hours: 1, direct: true, mileage: ['skypass', 'asiana'] },
    MXP: { hours: 12, direct: true, mileage: ['skypass'] },
    MUC: { hours: 11, direct: true, mileage: ['skypass', 'miles_and_more'] },
    LAS: { hours: 12, direct: false, mileage: ['skypass'] },
    SLC: { hours: 12, direct: false, mileage: [] },
    PHX: { hours: 12, direct: false, mileage: [] },
    DEN: { hours: 13, direct: false, mileage: [] },
    FLG: { hours: 12, direct: false, mileage: [] },
    VCE: { hours: 12, direct: false, mileage: [] },
    VRN: { hours: 13, direct: false, mileage: [] },
    INN: { hours: 11, direct: false, mileage: [] },
    TSF: { hours: 12, direct: false, mileage: [] },
    BZO: { hours: 12, direct: false, mileage: [] },
  },
  GMP: {
    KIX: { hours: 2, direct: true, mileage: ['skypass', 'asiana'] },
    NRT: { hours: 2, direct: true, mileage: ['skypass', 'asiana'] },
    HND: { hours: 2, direct: true, mileage: ['skypass', 'asiana'] },
    PUS: { hours: 1, direct: true, mileage: ['skypass', 'asiana'] },
    CJU: { hours: 1, direct: true, mileage: ['skypass', 'asiana'] },
    VCE: { hours: 12, direct: false, mileage: [] },
    MUC: { hours: 11, direct: false, mileage: [] },
    MXP: { hours: 12, direct: false, mileage: [] },
    LAS: { hours: 12, direct: false, mileage: ['skypass'] },
    SLC: { hours: 12, direct: false, mileage: [] },
    PHX: { hours: 12, direct: false, mileage: [] },
    DEN: { hours: 13, direct: false, mileage: [] },
    FLG: { hours: 12, direct: false, mileage: [] },
  },
  PUS: { ICN: { hours: 1, direct: true, mileage: ['skypass', 'asiana'] }, GMP: { hours: 1, direct: true, mileage: [] }, KIX: { hours: 2, direct: true, mileage: [] }, CJU: { hours: 1, direct: true, mileage: [] } },
};

/** 3자리 공항 코드인지 확인 */
function isAirportCode(str) {
  return /^[A-Z]{3}$/i.test((str || '').trim());
}

function findCityKey(name) {
  if (!name || typeof name !== 'string') return null;
  const t = name.trim();
  if (!t) return null;
  const tl = t.toLowerCase();
  // 사용자 입력에 등록 도시명이 포함되는 경우만 (예: "돌로미티 3박") — k.includes(t)는 "도" 등 짧은 문자로 돌로미티 오인식 가능성이 있어 제외
  return Object.keys(CITY_AIRPORTS).find((k) => {
    const kl = k.toLowerCase();
    return tl.includes(kl);
  }) || null;
}

/** IATA → 국가(알려진 코드만). CITY_AIRPORTS에서 수집 */
function getCountryForIata(code) {
  if (!code || typeof code !== 'string') return null;
  const c = code.trim().toUpperCase().slice(0, 3);
  for (const list of Object.values(CITY_AIRPORTS)) {
    for (const a of list) {
      if (a.code === c) return a.country || null;
    }
  }
  return null;
}

/**
 * 도시/관광지 문자열 또는 공항 코드로 앵커 국가(ISO2) 추정
 */
function resolveAnchorCountry(placeInput, selectedAirportCode) {
  if (selectedAirportCode && isAirportCode(selectedAirportCode)) {
    const g = getCountryForIata(selectedAirportCode);
    if (g) return g;
  }
  const key = findCityKey(placeInput || '');
  if (key && CITY_COUNTRY[key]) return CITY_COUNTRY[key];
  if (placeInput && isAirportCode(placeInput)) return getCountryForIata(placeInput);
  return null;
}

/**
 * 국내선 여부: 출발지·목적지가 같은 국가(도시명/공항코드 기준)
 */
function isDomesticRoute(originStr, destStr, originAirportCode, destAirportCode) {
  let co = resolveAnchorCountry(originStr, originAirportCode);
  let cd = resolveAnchorCountry(destStr, destAirportCode);
  if (!co && originStr && isAirportCode(originStr)) co = getCountryForIata(originStr);
  if (!cd && destStr && isAirportCode(destStr)) cd = getCountryForIata(destStr);
  if (co && cd) return co === cd;
  return false;
}

/** 지상·해상 이동 규칙으로 후보 필터·1차 정렬 (같은 나라 우선 → 거리순) */
function applyGroundAccessRules(airports, anchorCountry, domesticRoute) {
  if (!airports || !airports.length) return [];
  let list = airports;
  if (domesticRoute) {
    const ge3 = airports.filter((a) => (a.drive_hours || 0) >= 3);
    list = ge3.length ? ge3 : airports.filter((a) => (a.drive_hours || 0) <= 8);
    if (!list.length) list = [...airports];
  } else {
    list = airports.filter((a) => (a.drive_hours || 0) <= 8);
    if (!list.length) list = [...airports];
  }
  const ac = anchorCountry || '';
  return [...list].sort((a, b) => {
    const ca = a.country || '';
    const cb = b.country || '';
    const sa = ac && ca === ac ? 0 : 1;
    const sb = ac && cb === ac ? 0 : 1;
    if (sa !== sb) return sa - sb;
    return (a.drive_hours || 0) - (b.drive_hours || 0);
  });
}

/** 도시명으로 공항 목록 조회. 일치 없으면 null */
function getAirportsForCity(name) {
  if (!name || isAirportCode(name)) return null;
  const key = findCityKey(name);
  return key ? CITY_AIRPORTS[key] : null;
}

/** 마일리지 프로그램명 → 정규화 키 */
function normalizeMileageProgram(name) {
  if (!name || typeof name !== 'string') return '';
  const n = name.toLowerCase().replace(/\s/g, '');
  if (n.includes('skypass') || n.includes('대한항공')) return 'skypass';
  if (n.includes('asiana') || n.includes('아시아나')) return 'asiana';
  if (n.includes('milesandmore') || n.includes('miles_and_more') || n.includes('루프트한자')) return 'miles_and_more';
  return n || '';
}

/**
 * 출발지/목적지 공항 선택용 목록 (지상 규칙 + 비행·마일리지 보조 정렬)
 * @param {'origin'|'destination'} role
 */
function getAirportsForPlaceWithGroundRules(placeName, role, ctx) {
  const raw = getAirportsForCity(placeName);
  if (!raw) return null;
  const {
    originInput,
    destInput,
    originAirportCode,
    destAirportCode,
    domesticRoute,
    anchorCountry,
  } = ctx || {};
  const domestic = domesticRoute || isDomesticRoute(
    originInput || '',
    destInput || '',
    originAirportCode,
    destAirportCode,
  );
  const anchor = anchorCountry || (role === 'origin'
    ? resolveAnchorCountry(originInput, originAirportCode)
    : resolveAnchorCountry(destInput, destAirportCode));
  return applyGroundAccessRules(raw, anchor, domestic);
}

/**
 * 목적지 공항 목록
 * 1) 국제: 같은 나라(목적지) → 차량 거리 → (보조) 비행·마일리지
 * 2) 국내: 차량 3h 이상(완화 시 8h 이내) → 같은 나라 → 거리 → (보조) 비행·마일리지
 */
function getDestAirportsForOrigin(originCode, destCityName, options) {
  const dest = getAirportsForPlaceWithGroundRules(destCityName, 'destination', options?.routeContext);
  if (!dest) return null;
  const info = FLIGHT_INFO[originCode] || {};
  const mileageKey = normalizeMileageProgram(options?.mileageProgram);
  const ctx = options?.routeContext || {};
  const anchor = resolveAnchorCountry(destCityName, ctx.destAirportCode);
  const oc = (originCode || '').toString().trim().toUpperCase().slice(0, 3);
  const originGeo = AIRPORT_COORDS[oc];
  const regionKey = findCityKey(destCityName || '');
  const sortByOriginProximity =
    originGeo && regionKey && REGION_COLLECTION_KEYS.has(regionKey);

  return [...dest].sort((a, b) => {
    if (sortByOriginProximity) {
      const ca = AIRPORT_COORDS[a.code];
      const cb = AIRPORT_COORDS[b.code];
      if (ca && cb) {
        const dkm = haversineKm(originGeo.lat, originGeo.lng, ca.lat, ca.lng) -
          haversineKm(originGeo.lat, originGeo.lng, cb.lat, cb.lng);
        if (Math.abs(dkm) > 30) return dkm;
      }
    }
    const sa = anchor && a.country === anchor ? 0 : 1;
    const sb = anchor && b.country === anchor ? 0 : 1;
    if (sa !== sb) return sa - sb;
    const da = a.drive_hours || 0;
    const db = b.drive_hours || 0;
    if (da !== db) return da - db;

    const fa = info[a.code] || { hours: 99, direct: false, mileage: [] };
    const fb = info[b.code] || { hours: 99, direct: false, mileage: [] };
    const aHasMileageDirect = mileageKey && fa.direct && fa.mileage.includes(mileageKey);
    const bHasMileageDirect = mileageKey && fb.direct && fb.mileage.includes(mileageKey);
    if (aHasMileageDirect !== bHasMileageDirect) return aHasMileageDirect ? -1 : 1;
    if (fa.direct !== fb.direct) return fa.direct ? -1 : 1;
    return fa.hours - fb.hours;
  });
}
