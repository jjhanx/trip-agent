/**
 * 8시간 이내 공항 목록 (Mock)
 * 도시/관광지 이름 → 접근 가능 공항 코드
 * 실제 구현 시 교통 API로 지상·해상 8시간 이내 공항 조회
 */
const CITY_AIRPORTS = {
  '서울': [
    { code: 'ICN', name: '인천국제공항', drive_hours: 1 },
    { code: 'GMP', name: '김포국제공항', drive_hours: 0.5 },
  ],
  '인천': [
    { code: 'ICN', name: '인천국제공항', drive_hours: 0.5 },
    { code: 'GMP', name: '김포국제공항', drive_hours: 1 },
  ],
  '부산': [
    { code: 'PUS', name: '김해국제공항', drive_hours: 0.5 },
    { code: 'GMP', name: '김포국제공항', drive_hours: 4 },
    { code: 'ICN', name: '인천국제공항', drive_hours: 4.5 },
  ],
  '제주': [{ code: 'CJU', name: '제주국제공항', drive_hours: 0.3 }],
  '오사카': [
    { code: 'KIX', name: '간사이국제공항', drive_hours: 1 },
    { code: 'ITM', name: '오사카(이타미)', drive_hours: 0.5 },
  ],
  '도쿄': [
    { code: 'NRT', name: '나리타국제공항', drive_hours: 1.5 },
    { code: 'HND', name: '하네다공항', drive_hours: 0.5 },
  ],
  '방콕': [
    { code: 'BKK', name: '수완나품국제공항', drive_hours: 0.5 },
    { code: 'DMK', name: '돈므앙공항', drive_hours: 1 },
  ],
  '싱가포르': [{ code: 'SIN', name: '창이공항', drive_hours: 0.5 }],
  '홍콩': [{ code: 'HKG', name: '홍콩국제공항', drive_hours: 0.5 }],
  '돌로미티': [
    { code: 'MXP', name: '밀라노 말펜사', drive_hours: 3.5 },
    { code: 'VCE', name: '베니스 마르코폴로', drive_hours: 2 },
    { code: 'VRN', name: '베로나', drive_hours: 2 },
    { code: 'INN', name: '인스부르크', drive_hours: 2 },
    { code: 'TSF', name: '베니스 트레비소', drive_hours: 2.5 },
    { code: 'MUC', name: '뮌헨', drive_hours: 4 },
    { code: 'BZO', name: '볼차노', drive_hours: 1.5 },
  ],
  '도로미티': [
    { code: 'MXP', name: '밀라노 말펜사', drive_hours: 3.5 },
    { code: 'VCE', name: '베니스 마르코폴로', drive_hours: 2 },
    { code: 'VRN', name: '베로나', drive_hours: 2 },
    { code: 'INN', name: '인스부르크', drive_hours: 2 },
    { code: 'TSF', name: '베니스 트레비소', drive_hours: 2.5 },
    { code: 'MUC', name: '뮌헨', drive_hours: 4 },
    { code: 'BZO', name: '볼차노', drive_hours: 1.5 },
  ],
};

/**
 * 출발 공항 → 목적지 공항별 운항 정보
 * direct: 직항 여부, mileage: 해당 공항 직항이 있는 마일리지 프로그램 (skypass=대한항공 등)
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
  },
  PUS: { ICN: { hours: 1, direct: true, mileage: ['skypass', 'asiana'] }, GMP: { hours: 1, direct: true, mileage: [] }, KIX: { hours: 2, direct: true, mileage: [] }, CJU: { hours: 1, direct: true, mileage: [] } },
};

/** 3자리 공항 코드인지 확인 */
function isAirportCode(str) {
  return /^[A-Z]{3}$/i.test((str || '').trim());
}

/** 도시명으로 8시간 이내 공항 조회. 일치 없으면 null */
function getAirportsForCity(name) {
  if (!name || isAirportCode(name)) return null;
  const key = Object.keys(CITY_AIRPORTS).find(
    (k) => name.includes(k) || k.includes(name.trim())
  );
  return key ? CITY_AIRPORTS[key] : null;
}

/** 마일리지 프로그램명 → 정규화 키 (skypass, asiana, miles_and_more 등) */
function normalizeMileageProgram(name) {
  if (!name || typeof name !== 'string') return '';
  const n = name.toLowerCase().replace(/\s/g, '');
  if (n.includes('skypass') || n.includes('대한항공')) return 'skypass';
  if (n.includes('asiana') || n.includes('아시아나')) return 'asiana';
  if (n.includes('milesandmore') || n.includes('miles_and_more') || n.includes('루프트한자')) return 'miles_and_more';
  return n || '';
}

/**
 * 목적지 공항 목록
 * 정렬: 1) 마일리지 직항 공항 최우선 2) 직항 우선 3) 비행시간 짧은 순
 * (mileageProgram만 있어도 마일리지 직항 우선 - 적립 생각 시 use_miles 불필요)
 */
function getDestAirportsForOrigin(originCode, destCityName, options) {
  const dest = getAirportsForCity(destCityName);
  if (!dest) return null;
  const info = FLIGHT_INFO[originCode] || {};
  const mileageKey = normalizeMileageProgram(options?.mileageProgram);

  return [...dest].sort((a, b) => {
    const fa = info[a.code] || { hours: 99, direct: false, mileage: [] };
    const fb = info[b.code] || { hours: 99, direct: false, mileage: [] };
    const aHasMileageDirect = mileageKey && fa.direct && fa.mileage.includes(mileageKey);
    const bHasMileageDirect = mileageKey && fb.direct && fb.mileage.includes(mileageKey);

    // 1) 마일리지 직항 공항 최우선 (돌로미티+Skypass → MXP 1순위)
    if (aHasMileageDirect !== bHasMileageDirect) return aHasMileageDirect ? -1 : 1;
    // 2) 직항 우선
    if (fa.direct !== fb.direct) return fa.direct ? -1 : 1;
    // 3) 비행시간 짧은 순
    return fa.hours - fb.hours;
  });
}
