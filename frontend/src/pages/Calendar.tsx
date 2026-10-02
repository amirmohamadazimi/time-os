import {
  ActionIcon, Alert, Anchor, Badge, Button, Checkbox, Group, List, Loader, Paper, PasswordInput, SimpleGrid, Stack,
  Switch, Text, TextInput, Title,
} from "@mantine/core";
import { IconChevronLeft, IconChevronRight, IconRefresh, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useState } from "react";
import { endpoints } from "../api/endpoints";
import type { CalendarAccount, CalendarEvent } from "../api/types";
import { FreeTimeSummary } from "../components/FreeTimeSummary";
import { useAppMutation } from "../hooks/useFocus";
import { useCalendarAutoSync } from "../hooks/useCalendar";
import { formatDateTime, formatTime, isoDate } from "../lib/format";
import { notifyError, notifyOk } from "../lib/notify";

/** Paste Google Calendar's secret iCal address. Read-only: Time OS never changes the calendar. */
function ConnectForm({ first }: { first: boolean }) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [allDayBusy, setAllDayBusy] = useState(false);
  const connect = useAppMutation(
    () => endpoints.connectIcal({ url: url.trim(), name: name.trim() || null, all_day_busy: allDayBusy }),
    (account) => {
      notifyOk(`Connected ${account.display_name}`);
      setUrl("");
      setName("");
    },
  );
  return (
    <Paper withBorder p="md">
      <Title order={4}>{first ? "Connect Google Calendar" : "Add another calendar"}</Title>
      <Text size="sm" c="dimmed" mb="sm">
        Read-only: Time OS reads your events to know when you are busy and never changes your calendar.
        No Google Cloud setup is needed.
      </Text>
      <List size="sm" type="ordered" mb="sm">
        <List.Item>
          Open <Anchor href="https://calendar.google.com/calendar/r/settings" target="_blank" rel="noreferrer">
            Google Calendar settings</Anchor> on a computer.
        </List.Item>
        <List.Item>Under <b>Settings for my calendars</b>, click your calendar, then <b>Integrate calendar</b>.</List.Item>
        <List.Item>Copy <b>Secret address in iCal format</b> and paste it below.</List.Item>
      </List>
      <Text size="xs" c="dimmed" mb="sm">
        Anyone with that link can see your calendar, so Time OS stores it encrypted and never shows it again.
        If it leaks, use <b>Reset</b> next to it in Google Calendar and connect the new one.
      </Text>
      <Stack gap="sm">
        <PasswordInput label="Secret address in iCal format" placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"
          value={url} onChange={(e) => setUrl(e.currentTarget.value)} />
        <Group align="end">
          <TextInput label="Name (optional)" placeholder="Taken from the calendar" value={name}
            onChange={(e) => setName(e.currentTarget.value)} />
          <Checkbox label="Holidays and other all-day events block time" checked={allDayBusy}
            onChange={(e) => setAllDayBusy(e.currentTarget.checked)} mb={8} />
        </Group>
        <Button w="fit-content" disabled={url.trim().length < 10} loading={connect.isPending}
          onClick={() => connect.mutate(undefined)}>
          Connect
        </Button>
      </Stack>
    </Paper>
  );
}

function Feed({ account }: { account: CalendarAccount }) {
  const [calendar] = account.calendars;
  const update = useAppMutation((body: { selected?: boolean; all_day_busy?: boolean }) =>
    endpoints.updateCalendar(calendar.id, body));
  const remove = useAppMutation(() => endpoints.disconnectCalendar(account.id), () => notifyOk("Calendar disconnected"));
  if (!calendar) return null;
  return (
    <Paper withBorder p="md">
      <Group justify="space-between" wrap="nowrap" align="start">
        <Stack gap={2}>
          <Group gap={6}>
            <Text fw={600}>{calendar.summary}</Text>
            <Badge size="sm" variant="light" color="gray">read-only</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {account.feed_host} · read {calendar.last_synced_at ? formatDateTime(calendar.last_synced_at) : "never"}
            {calendar.timezone ? ` · ${calendar.timezone}` : ""}
          </Text>
        </Stack>
        <ActionIcon variant="subtle" color="red" aria-label="Disconnect" loading={remove.isPending}
          onClick={() => {
            if (window.confirm(`Disconnect "${calendar.summary}"? Its link and cached events are removed from Time OS.`)) {
              remove.mutate(undefined);
            }
          }}>
          <IconTrash size={16} />
        </ActionIcon>
      </Group>
      {calendar.last_error && <Alert color="red" mt="sm" title="Last sync failed">{calendar.last_error}</Alert>}
      <Group mt="sm">
        <Switch label="Show and plan around it" checked={calendar.selected}
          onChange={(e) => update.mutate({ selected: e.currentTarget.checked })} />
        <Switch label="All-day events block time" checked={calendar.all_day_busy}
          onChange={(e) => update.mutate({ all_day_busy: e.currentTarget.checked })} />
      </Group>
    </Paper>
  );
}

function EventRow({ event }: { event: CalendarEvent }) {
  return (
    <Group gap="sm" wrap="nowrap" align="start" py={4} style={{ opacity: event.busy ? 1 : 0.65 }}>
      <Text size="sm" w={96} c="dimmed" style={{ flexShrink: 0 }}>
        {event.all_day ? "All day" : `${formatTime(event.start_time)}–${formatTime(event.end_time)}`}
      </Text>
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Group gap={6}>
          <Text size="sm" fw={500}>{event.title}</Text>
          {!event.busy && <Badge size="xs" variant="light" color="gray">free</Badge>}
          {event.status === "tentative" && <Badge size="xs" variant="light" color="yellow">tentative</Badge>}
        </Group>
        {event.location && <Text size="xs" c="dimmed" truncate>{event.location}</Text>}
      </Stack>
    </Group>
  );
}

function Agenda({ start }: { start: dayjs.Dayjs }) {
  const days = Array.from({ length: 7 }, (_, i) => start.add(i, "day"));
  const events = useQuery({
    queryKey: ["calendar-events", isoDate(days[0]), isoDate(days[6])],
    queryFn: () => endpoints.calendarEvents(isoDate(days[0]), isoDate(days[6])),
  });
  if (events.isLoading) return <Loader />;
  const byDay = (day: dayjs.Dayjs) =>
    (events.data ?? []).filter((e) =>
      e.all_day ? dayjs(e.start_time).isSame(day, "day") || (dayjs(e.start_time).isBefore(day) && dayjs(e.end_time).isAfter(day))
        : dayjs(e.start_time).isSame(day, "day"));
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }}>
      {days.map((day) => {
        const items = byDay(day);
        return (
          <Paper key={day.toString()} withBorder p="sm">
            <Text fw={600} size="sm" c={day.isSame(dayjs(), "day") ? "blue" : undefined}>{day.format("dddd D MMM")}</Text>
            {items.length === 0 ? <Text size="sm" c="dimmed">No events</Text>
              : items.map((e) => <EventRow key={e.id} event={e} />)}
          </Paper>
        );
      })}
    </SimpleGrid>
  );
}

export function CalendarPage() {
  const accounts = useQuery({ queryKey: ["calendar-accounts"], queryFn: endpoints.calendarAccounts });
  const connected = (accounts.data ?? []).length > 0;
  const autoSync = useCalendarAutoSync(connected);
  const [start, setStart] = useState(() => dayjs().startOf("day"));
  const today = isoDate(dayjs());
  const free = useQuery({
    queryKey: ["calendar-free", today], queryFn: () => endpoints.freeTime(today), enabled: connected,
  });
  const sync = useAppMutation(() => endpoints.syncCalendars({ force: true }), (results) => {
    const failed = results.find((r) => r.status === "error");
    if (failed) notifyError(`${failed.summary}: ${failed.error}`);
    else notifyOk("Calendar updated");
  });
  if (accounts.isLoading) return <Loader />;
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Calendar</Title>
        {connected && (
          <Button variant="light" leftSection={<IconRefresh size={16} />} loading={sync.isPending || autoSync.isFetching}
            onClick={() => sync.mutate(undefined)}>
            Sync now
          </Button>
        )}
      </Group>
      {!connected ? <ConnectForm first /> : (
        <>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Paper withBorder p="md">
              <Title order={5} mb="xs">Today inside working hours</Title>
              {free.data ? <FreeTimeSummary free={free.data} /> : <Loader size="sm" />}
            </Paper>
            <Stack>
              {accounts.data!.map((a) => <Feed key={a.id} account={a} />)}
            </Stack>
          </SimpleGrid>
          <Group justify="space-between">
            <Title order={4}>{start.format("D MMM")} – {start.add(6, "day").format("D MMM")}</Title>
            <Group gap={4}>
              <ActionIcon variant="default" aria-label="Previous week" onClick={() => setStart(start.subtract(7, "day"))}>
                <IconChevronLeft size={16} />
              </ActionIcon>
              <Button variant="default" size="xs" onClick={() => setStart(dayjs().startOf("day"))}>Today</Button>
              <ActionIcon variant="default" aria-label="Next week" onClick={() => setStart(start.add(7, "day"))}>
                <IconChevronRight size={16} />
              </ActionIcon>
            </Group>
          </Group>
          <Text size="xs" c="dimmed">Events from the last 30 days and the next 90 days are kept in sync.</Text>
          <Agenda start={start} />
          <ConnectForm first={false} />
        </>
      )}
    </Stack>
  );
}
