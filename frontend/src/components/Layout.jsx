import { useState, useEffect } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Calendar,
  Users,
  Phone,
  BarChart3,
  Settings,
  Shield,
  LogOut,
  Menu,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '../contexts/AuthContext'

const NAV_ITEMS = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard },
  { label: 'Appointments', path: '/appointments', icon: Calendar },
  { label: 'Patients', path: '/patients', icon: Users },
  { label: 'Call Log', path: '/calls', icon: Phone },
  { label: 'Analytics', path: '/analytics', icon: BarChart3 },
  {
    label: 'Settings',
    path: '/settings',
    icon: Settings,
    roles: ['practice_admin', 'super_admin'],
  },
  {
    label: 'Super Admin',
    path: '/admin',
    icon: Shield,
    roles: ['super_admin'],
  },
]

function roleBadgeColor(role) {
  switch (role) {
    case 'super_admin':
      return 'bg-purple-100 text-purple-700'
    case 'practice_admin':
      return 'bg-primary-100 text-primary-700'
    case 'staff':
      return 'bg-green-100 text-green-700'
    default:
      return 'bg-gray-100 text-gray-700'
  }
}

function formatRole(role) {
  if (!role) return 'User'
  return role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function Layout() {
  const { user, logout } = useAuth()
  const location = useLocation()

  // Sidebar collapsed state (desktop)
  const [collapsed, setCollapsed] = useState(false)
  // Mobile drawer open state
  const [mobileOpen, setMobileOpen] = useState(false)

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  // Close mobile drawer on window resize past md breakpoint
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) {
        setMobileOpen(false)
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const displayName = user
    ? [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email
    : 'User'

  const filteredNav = NAV_ITEMS.filter((item) => {
    if (!item.roles) return true
    return user && item.roles.includes(user.role)
  })

  // Shared sidebar content renderer
  function renderNav(isMobile = false) {
    return (
      <nav aria-label="Main navigation" className="flex-1 py-4 space-y-1 px-3 overflow-y-auto">
        {filteredNav.map((item) => {
          const Icon = item.icon
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path)

          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={clsx(
                'group flex items-center rounded-lg text-sm font-medium transition-all duration-200',
                isMobile || !collapsed ? 'px-3 py-2.5 gap-3' : 'justify-center px-2 py-2.5',
                isActive
                  ? 'bg-primary-600 text-white shadow-lg shadow-primary-600/25'
                  : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              )}
              title={collapsed && !isMobile ? item.label : undefined}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon
                className={clsx(
                  'flex-shrink-0 transition-colors',
                  isMobile || !collapsed ? 'w-5 h-5' : 'w-5 h-5',
                  isActive
                    ? 'text-white'
                    : 'text-slate-400 group-hover:text-white'
                )}
              />
              {(isMobile || !collapsed) && <span>{item.label}</span>}
            </NavLink>
          )
        })}
      </nav>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Skip to main content — visible only on keyboard focus */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:bg-primary-600 focus:text-white focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm focus:font-medium"
      >
        Skip to main content
      </a>

      {/* ============================================================
          MOBILE OVERLAY
          ============================================================ */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ============================================================
          MOBILE SIDEBAR DRAWER
          ============================================================ */}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-50 w-64 bg-slate-900 flex flex-col transition-transform duration-300 ease-in-out md:hidden',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Logo / Brand */}
        <div className="flex items-center justify-between h-16 px-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary-600 flex items-center justify-center">
              <Phone className="w-4 h-4 text-white" />
            </div>
            <span className="text-white font-semibold text-sm leading-tight">
              AI Medical<br />Receptionist
            </span>
          </div>
          <button
            onClick={() => setMobileOpen(false)}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            aria-label="Close navigation menu"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {renderNav(true)}

        {/* User section */}
        <div className="border-t border-slate-800 p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-bold uppercase">
              {user?.first_name?.[0] || user?.email?.[0] || 'U'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-white truncate">{displayName}</p>
              <p className="text-xs text-slate-400 truncate">{formatRole(user?.role)}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
            <span>Logout</span>
          </button>
        </div>
      </aside>

      {/* ============================================================
          DESKTOP SIDEBAR
          ============================================================ */}
      <aside
        className={clsx(
          'hidden md:flex md:flex-col md:fixed md:inset-y-0 md:left-0 bg-slate-900 z-30 transition-all duration-300 ease-in-out',
          collapsed ? 'md:w-[68px]' : 'md:w-64'
        )}
      >
        {/* Logo / Brand */}
        <div
          className={clsx(
            'flex items-center h-16 border-b border-slate-800',
            collapsed ? 'justify-center px-2' : 'px-4 gap-3'
          )}
        >
          <div className="w-8 h-8 rounded-lg bg-primary-600 flex items-center justify-center flex-shrink-0">
            <Phone className="w-4 h-4 text-white" />
          </div>
          {!collapsed && (
            <span className="text-white font-semibold text-sm leading-tight">
              AI Medical<br />Receptionist
            </span>
          )}
        </div>

        {renderNav(false)}

        {/* Collapse toggle */}
        <div className="px-3 pb-2">
          <button
            onClick={() => setCollapsed((prev) => !prev)}
            className={clsx(
              'flex items-center rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors w-full',
              collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5 gap-3'
            )}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <ChevronRight className="w-5 h-5" />
            ) : (
              <>
                <ChevronLeft className="w-5 h-5" />
                <span>Collapse</span>
              </>
            )}
          </button>
        </div>

        {/* User section */}
        <div className="border-t border-slate-800 p-3">
          {collapsed ? (
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-bold uppercase">
                {user?.first_name?.[0] || user?.email?.[0] || 'U'}
              </div>
              <button
                onClick={logout}
                className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-bold uppercase flex-shrink-0">
                  {user?.first_name?.[0] || user?.email?.[0] || 'U'}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-white truncate">{displayName}</p>
                  <p className="text-xs text-slate-400 truncate">{formatRole(user?.role)}</p>
                </div>
              </div>
              <button
                onClick={logout}
                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" />
                <span>Logout</span>
              </button>
            </>
          )}
        </div>
      </aside>

      {/* ============================================================
          MAIN CONTENT WRAPPER
          ============================================================ */}
      <div
        className={clsx(
          'flex-1 flex flex-col min-h-screen transition-all duration-300 ease-in-out',
          collapsed ? 'md:ml-[68px]' : 'md:ml-64'
        )}
      >
        {/* ---- Top Header Bar ---- */}
        <header className="sticky top-0 z-20 bg-white border-b border-gray-200 shadow-sm">
          <div className="flex items-center justify-between h-16 px-4 sm:px-6">
            {/* Left: hamburger (mobile) + title */}
            <div className="flex items-center gap-3">
              <button
                onClick={() => setMobileOpen(true)}
                className="p-2 -ml-2 rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors md:hidden"
                aria-label="Open navigation menu"
              >
                <Menu className="w-5 h-5" aria-hidden="true" />
              </button>
              <h1 className="text-lg font-semibold text-gray-900 hidden sm:block">
                AI Medical Receptionist
              </h1>
            </div>

            {/* Right: user info + logout */}
            <div className="flex items-center gap-3">
              <div className="hidden sm:flex items-center gap-2">
                <span className="text-sm font-medium text-gray-700">{displayName}</span>
                <span
                  className={clsx(
                    'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                    roleBadgeColor(user?.role)
                  )}
                >
                  {formatRole(user?.role)}
                </span>
              </div>
              <button
                onClick={logout}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
                <span className="hidden sm:inline">Logout</span>
              </button>
            </div>
          </div>
        </header>

        {/* ---- Page content ---- */}
        <main id="main-content" className="flex-1 p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
