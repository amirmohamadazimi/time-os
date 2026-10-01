import { AppShell, Badge, Burger, Group, NavLink, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconCalendar, IconChartBar, IconClock, IconFileImport, IconFolders, IconHistory, IconLayoutDashboard,
  IconListCheck, IconSettings,
} from "@tabler/icons-react";
import { NavLink as RouterLink, Route, Routes, useLocation } from "react-router-dom";
import { useCurrentSession } from "./hooks/useFocus";
import { formatClock } from "./lib/format";
import { AnalyticsPage } from "./pages/Analytics";
import { CalendarPage } from "./pages/Calendar";
import { DashboardPage } from "./pages/Dashboard";
import { FocusPage } from "./pages/Focus";
import { ImportPage } from "./pages/Import";
import { ProjectsPage } from "./pages/Projects";
import { SessionsPage } from "./pages/Sessions";
import { SettingsPage } from "./pages/Settings";
import { TasksPage } from "./pages/Tasks";

const NAV = [
  { to: "/", label: "Dashboard", icon: IconLayoutDashboard },
  { to: "/calendar", label: "Calendar", icon: IconCalendar },
  { to: "/tasks", label: "Tasks", icon: IconListCheck },
  { to: "/projects", label: "Projects", icon: IconFolders },
  { to: "/focus", label: "Focus", icon: IconClock },
  { to: "/sessions", label: "Sessions", icon: IconHistory },
  { to: "/analytics", label: "Analytics", icon: IconChartBar },
  { to: "/import", label: "Import", icon: IconFileImport },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

function LiveBadge() {
  const { session, active } = useCurrentSession();
  if (!session) return null;
  return (
    <Badge component={RouterLink} to="/focus" size="lg" variant="light" color={session.state === "paused" ? "yellow" : "teal"}
      style={{ cursor: "pointer" }}>
      {session.state === "paused" ? "Paused" : session.type === "rest" ? "Break" : "Focus"} · {formatClock(active)}
    </Badge>
  );
}

export function App() {
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4}>Time OS</Title>
            <Text size="xs" c="dimmed" visibleFrom="sm">plan · time · behaviour</Text>
          </Group>
          <LiveBadge />
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} component={RouterLink} to={to} label={label} leftSection={<Icon size={18} />}
            active={to === "/" ? location.pathname === "/" : location.pathname.startsWith(to)} onClick={close} />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/focus" element={<FocusPage />} />
          <Route path="/sessions" element={<SessionsPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  );
}
