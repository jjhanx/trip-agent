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
    { code: 'VCE', name: '베니스 마르코폴로', drive_hours: 2 },
    { code: 'VRN', name: '베로나', drive_hours: 2 },
    { code: 'INN', name: '인스부르크', drive_hours: 2 },
    { code: 'TSF', name: '베니스 트레비소', drive_hours: 2.5 },
    { code: 'MUC', name: '뮌헨', drive_hours: 4 },
    { code: 'BZO', name: '볼차노', drive_hours: 1.5 },
  ],
  '도로미티': [
    { code: 'VCE', name: '베니스 마르코폴로', drive_hours: 2 },
    { code: 'VRN', name: '베로나', drive_hours: 2 },
    { code: 'INN', name: '인스부르크', drive_hours: 2 },
    { code: 'TSF', name: '베니스 트레비소', drive_hours: 2.5 },
    { code: 'MUC', name: '뮌헨', drive_hours: 4 },
    { code: 'BZO', name: '볼차노', drive_hours: 1.5 },
  ],
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

/** 목적지 공항 목록 (출발 공항 기준 비행시간 짧은 순 Mock) */
function getDestAirportsForOrigin(originCode, destCityName) {
  const dest = getAirportsForCity(destCityName);
  if (!dest) return null;
  // Mock: origin에 따라 정렬. 실제로는 비행시간 API 호출
  const flightTime = {
    ICN: { KIX: 2, NRT: 2, HND: 2, BKK: 5, SIN: 6, HKG: 4, PUS: 1, CJU: 1, VCE: 12, MUC: 11, VRN: 12, INN: 11, TSF: 12, BZO: 12 },
    GMP: { KIX: 2, NRT: 2, HND: 2, PUS: 1, CJU: 1, VCE: 12, MUC: 11 },
    PUS: { ICN: 1, GMP: 1, KIX: 2, CJU: 1 },
  };
  const times = flightTime[originCode] || {};
  return [...dest].sort(
    (a, b) => (times[a.code] ?? 99) - (times[b.code] ?? 99)
  );
}
