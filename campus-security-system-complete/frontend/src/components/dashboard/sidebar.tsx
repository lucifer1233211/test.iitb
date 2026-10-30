'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/auth-context'
import { PERMISSIONS } from '@/types/auth'
import {
  Shield,
  Camera,
  Users,
  AlertTriangle,
  BarChart3,
  Settings,
  FileText,
  Eye,
  UserPlus,
  Activity,
  Database,
  Bell,
  Lock,
  ChevronDown,
  ChevronRight,
  ScanFace,
  Video,
  Upload,
  Radio,
} from 'lucide-react'

interface NavigationItem {
  name: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  permission?: string
  children?: NavigationItem[]
}

const navigation: NavigationItem[] = [
  {
    name: 'Dashboard',
    href: '/dashboard',
    icon: BarChart3,
  },
  {
    name: 'Live Monitoring',
    href: '/dashboard/monitoring',
    icon: Eye,
    permission: PERMISSIONS.CAMERA_READ,
  },
  {
    name: 'Face Recognition',
    href: '/dashboard/face-recognition',
    icon: Users,
    permission: PERMISSIONS.FACE_VIEW,
    children: [
      {
        name: 'Enrolled Persons',
        href: '/dashboard/face-recognition/persons',
        icon: Users,
        permission: PERMISSIONS.FACE_VIEW,
      },
      {
        name: 'Enroll New Person',
        href: '/dashboard/face-recognition/enroll',
        icon: UserPlus,
        permission: PERMISSIONS.FACE_ENROLL,
      },
      {
        name: 'Detection History',
        href: '/dashboard/face-recognition/detections',
        icon: Activity,
        permission: PERMISSIONS.FACE_VIEW,
      },
      {
        name: 'Test Recognition',
        href: '/dashboard/face-recognition/test',
        icon: ScanFace,
        permission: PERMISSIONS.FACE_VIEW,
      },
    ],
  },
  {
    name: 'Video Analysis',
    href: '/dashboard/video-analysis',
    icon: Video,
    permission: PERMISSIONS.CAMERA_READ,
    children: [
      {
        name: 'Upload Video',
        href: '/dashboard/video-analysis',
        icon: Upload,
        permission: PERMISSIONS.CAMERA_READ,
      },
      {
        name: 'RTSP Streams',
        href: '/dashboard/video-analysis/rtsp',
        icon: Radio,
        permission: PERMISSIONS.CAMERA_READ,
      },
    ],
  },
  {
    name: 'Cameras',
    href: '/dashboard/cameras',
    icon: Camera,
    permission: PERMISSIONS.CAMERA_READ,
    children: [
      {
        name: 'Camera List',
        href: '/dashboard/cameras',
        icon: Camera,
        permission: PERMISSIONS.CAMERA_READ,
      },
      {
        name: 'Add Camera',
        href: '/dashboard/cameras/add',
        icon: Camera,
        permission: PERMISSIONS.CAMERA_CREATE,
      },
    ],
  },
  {
    name: 'Alerts',
    href: '/dashboard/alerts',
    icon: AlertTriangle,
    permission: PERMISSIONS.ALERT_READ,
  },
  {
    name: 'Analytics',
    href: '/dashboard/analytics',
    icon: BarChart3,
    permission: PERMISSIONS.ANALYTICS_VIEW,
  },
  {
    name: 'Reports',
    href: '/dashboard/reports',
    icon: FileText,
    permission: PERMISSIONS.REPORT_VIEW,
  },
  {
    name: 'User Management',
    href: '/dashboard/users',
    icon: Users,
    permission: PERMISSIONS.USER_READ,
  },
  {
    name: 'GCS',
    href: '/dashboard/gcs',
    icon: Radio,
    permission: PERMISSIONS.USER_READ,
  },
  {
    name: 'System',
    href: '/dashboard/system',
    icon: Settings,
    permission: PERMISSIONS.SYSTEM_CONFIG,
    children: [
      {
        name: 'Configuration',
        href: '/dashboard/system/config',
        icon: Settings,
        permission: PERMISSIONS.SYSTEM_CONFIG,
      },
      {
        name: 'Audit Logs',
        href: '/dashboard/system/audit',
        icon: FileText,
        permission: PERMISSIONS.AUDIT_VIEW,
      },
      {
        name: 'Database',
        href: '/dashboard/system/database',
        icon: Database,
        permission: PERMISSIONS.SYSTEM_CONFIG,
      },
    ],
  },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const pathname = usePathname()
  const { user } = useAuth()
  const [expandedItems, setExpandedItems] = useState<string[]>([])

  // Check if user has permission
  const hasPermission = (permission?: string) => {
    if (!permission) return true
    if (!user?.permissions) return false
    return user.permissions.some(p => p.name === permission)
  }

  // Filter navigation items based on permissions
  const filteredNavigation = navigation.filter(item => hasPermission(item.permission))

  const toggleExpanded = (itemName: string) => {
    setExpandedItems(prev => 
      prev.includes(itemName) 
        ? prev.filter(name => name !== itemName)
        : [...prev, itemName]
    )
  }

  const isExpanded = (itemName: string) => expandedItems.includes(itemName)

  const isActive = (href: string) => {
    if (href === '/dashboard') {
      return pathname === '/dashboard'
    }
    return pathname.startsWith(href)
  }

  const renderNavigationItem = (item: NavigationItem, level: number = 0) => {
    if (!hasPermission(item.permission)) return null

    const hasChildren = item.children && item.children.length > 0
    const expanded = isExpanded(item.name)
    const active = isActive(item.href)

    return (
      <div key={item.name}>
        <div className="relative">
          {hasChildren ? (
            <button
              onClick={() => toggleExpanded(item.name)}
              className={cn(
                'group flex w-full items-center rounded-md px-2 py-2 text-sm font-medium transition-colors',
                level > 0 && 'ml-4',
                active
                  ? 'bg-security-100 text-security-900 dark:bg-security-900 dark:text-security-100'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white'
              )}
            >
              <item.icon
                className={cn(
                  'mr-3 h-5 w-5 flex-shrink-0',
                  active
                    ? 'text-security-600 dark:text-security-400'
                    : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-500 dark:group-hover:text-gray-400'
                )}
              />
              <span className="flex-1 text-left">{item.name}</span>
              {expanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
          ) : (
            <Link
              href={item.href}
              onClick={onClose}
              className={cn(
                'group flex items-center rounded-md px-2 py-2 text-sm font-medium transition-colors',
                level > 0 && 'ml-4',
                active
                  ? 'bg-security-100 text-security-900 dark:bg-security-900 dark:text-security-100'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white'
              )}
            >
              <item.icon
                className={cn(
                  'mr-3 h-5 w-5 flex-shrink-0',
                  active
                    ? 'text-security-600 dark:text-security-400'
                    : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-500 dark:group-hover:text-gray-400'
                )}
              />
              {item.name}
            </Link>
          )}
        </div>

        {/* Render children if expanded */}
        {hasChildren && expanded && (
          <div className="mt-1 space-y-1">
            {item.children?.map(child => renderNavigationItem(child, level + 1))}
          </div>
        )}
      </div>
    )
  }

  return (
    <>
      {/* Desktop Sidebar */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-64 lg:flex-col">
        <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white px-6 pb-4 shadow-xl dark:bg-gray-900">
          {/* Logo */}
          <div className="flex h-16 shrink-0 items-center">
            <div className="flex items-center space-x-3">
              <img src="/iitb-logo.png" alt="IIT Bombay" className="h-9 w-9" />
              <div>
                <h1 className="text-sm font-semibold text-gray-900 dark:text-white leading-tight">
                  IIT Bombay
                </h1>
                <p className="text-[10px] text-muted-foreground leading-tight">Security System</p>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex flex-1 flex-col">
            <ul role="list" className="flex flex-1 flex-col gap-y-7">
              <li>
                <ul role="list" className="-mx-2 space-y-1">
                  {filteredNavigation.map(item => (
                    <li key={item.name}>
                      {renderNavigationItem(item)}
                    </li>
                  ))}
                </ul>
              </li>

              {/* User Info */}
              <li className="mt-auto">
                <div className="flex items-center gap-x-4 px-2 py-3 text-sm font-semibold leading-6 text-gray-900 dark:text-white">
                  <div className="h-8 w-8 rounded-full bg-security-600 flex items-center justify-center">
                    <span className="text-sm font-medium text-white">
                      {user?.full_name?.charAt(0) || 'U'}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {user?.full_name}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                      {user?.role?.name}
                    </p>
                  </div>
                </div>
              </li>
            </ul>
          </nav>
        </div>
      </div>

      {/* Mobile Sidebar */}
      <div className={cn(
        'fixed inset-0 z-50 lg:hidden',
        open ? 'block' : 'hidden'
      )}>
        <div className="fixed inset-y-0 left-0 z-50 w-64 bg-white px-6 pb-4 shadow-xl dark:bg-gray-900">
          <div className="flex grow flex-col gap-y-5 overflow-y-auto">
            {/* Logo */}
            <div className="flex h-16 shrink-0 items-center">
              <div className="flex items-center space-x-3">
                <img src="/iitb-logo.png" alt="IIT Bombay" className="h-9 w-9" />
                <div>
                  <h1 className="text-sm font-semibold text-gray-900 dark:text-white leading-tight">
                    IIT Bombay
                  </h1>
                  <p className="text-[10px] text-muted-foreground leading-tight">Security System</p>
                </div>
              </div>
            </div>

            {/* Navigation */}
            <nav className="flex flex-1 flex-col">
              <ul role="list" className="flex flex-1 flex-col gap-y-7">
                <li>
                  <ul role="list" className="-mx-2 space-y-1">
                    {filteredNavigation.map(item => (
                      <li key={item.name}>
                        {renderNavigationItem(item)}
                      </li>
                    ))}
                  </ul>
                </li>

                {/* User Info */}
                <li className="mt-auto">
                  <div className="flex items-center gap-x-4 px-2 py-3 text-sm font-semibold leading-6 text-gray-900 dark:text-white">
                    <div className="h-8 w-8 rounded-full bg-security-600 flex items-center justify-center">
                      <span className="text-sm font-medium text-white">
                        {user?.full_name?.charAt(0) || 'U'}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                        {user?.full_name}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                        {user?.role?.name}
                      </p>
                    </div>
                  </div>
                </li>
              </ul>
            </nav>
          </div>
        </div>
      </div>
    </>
  )
}
