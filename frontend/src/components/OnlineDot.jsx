/**
 * Small green/gray dot indicating online status.
 * Props: isOnline (boolean), size (number, default 8)
 */
export default function OnlineDot({ isOnline, size = 8 }) {
  return (
    <span
      className={`inline-block rounded-full flex-shrink-0 ${isOnline ? 'bg-positive pulse-live' : 'bg-zinc-600'}`}
      style={{ width: size, height: size }}
      title={isOnline ? 'Online now' : 'Offline'}
    />
  );
}
