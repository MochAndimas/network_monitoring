const WIB_PARTS_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Jakarta",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23"
});

function wibParts(value: Date) {
  const parts = WIB_PARTS_FORMATTER.formatToParts(value);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value;
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute"), second: get("second") };
}

/** Format an absolute timestamp as an explicit WIB boundary for server-side date filters. */
export function toWibOffsetTimestamp(value: Date) {
  const parts = wibParts(value);
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+07:00`;
}

export function toWibDate(value: Date) {
  const parts = wibParts(value);
  return `${parts.year}-${parts.month}-${parts.day}`;
}
