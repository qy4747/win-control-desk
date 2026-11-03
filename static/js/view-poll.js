// A view owns its request and timer. Retired requests cannot paint or reschedule.
export function viewPoll({ url, interval, timeout, onData, onError,
  fetcher = fetch, later = setTimeout, cancel = clearTimeout }) {
  let active = false, timer, flight;
  async function refresh() {
    cancel(timer);
    if (!active) return;
    flight?.abort();
    const controller = new AbortController();
    flight = controller;
    const deadline = later(() => controller.abort(), timeout);
    try {
      const response = await fetcher(url, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (flight === controller) onData(data);
    } catch (e) {
      if (flight === controller) onError(e);
    } finally {
      cancel(deadline);
      if (flight === controller) {
        flight = null;
        timer = later(refresh, interval);
      }
    }
  }
  return {
    refresh,
    setActive(value) {
      if (value === active) return;
      active = value;
      cancel(timer);
      const old = flight;
      flight = null;
      old?.abort();
      if (active) return refresh();
    },
  };
}
