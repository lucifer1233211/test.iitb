'use client'

import { useState } from 'react'
import { downloadFile } from '@/lib/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { FileText, Download, BarChart3, Shield, Camera, AlertCircle, CheckCircle2 } from 'lucide-react'

const reportTypes = [
  { id: 'security_summary', title: 'Security Summary', desc: 'Overview of security events and alerts', icon: Shield, color: 'text-blue-500' },
  { id: 'detection_report', title: 'Detection Report', desc: 'Face detection activity and identification stats', icon: BarChart3, color: 'text-green-500' },
  { id: 'camera_status', title: 'Camera Status Report', desc: 'Camera uptime, health, and maintenance logs', icon: Camera, color: 'text-purple-500' },
  { id: 'incident_log', title: 'Incident Log', desc: 'Detailed log of all security incidents', icon: FileText, color: 'text-orange-500' },
]

const toDateInputValue = (date: Date) => {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const initialDateRange = () => {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 6)
  return {
    start: toDateInputValue(start),
    end: toDateInputValue(end),
  }
}

export default function ReportsPage() {
  const [generating, setGenerating] = useState<string | null>(null)
  const [dateRange, setDateRange] = useState(initialDateRange)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleGenerate = async (reportId: string, reportTitle: string) => {
    setError('')
    setSuccess('')

    if (!dateRange.start || !dateRange.end) {
      setError('Select both start and end dates before generating a report.')
      return
    }

    if (dateRange.start > dateRange.end) {
      setError('Start date cannot be after end date.')
      return
    }

    setGenerating(reportId)
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start,
        end_date: dateRange.end,
      })
      const filename = `${reportId}_${dateRange.start}_to_${dateRange.end}.csv`
      await downloadFile(`/reports/${reportId}/download?${params.toString()}`, filename)
      setSuccess(`${reportTitle} downloaded for ${dateRange.start} to ${dateRange.end}.`)
    } catch (err: any) {
      setError(err?.detail || err?.response?.data?.detail || `Failed to generate ${reportTitle}.`)
    } finally {
      setGenerating(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <FileText className="h-6 w-6 text-blue-500" /> Reports
        </h1>
        <p className="text-gray-500 dark:text-gray-400">Generate and download security reports</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Date Range</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Start Date</label>
              <input type="date" value={dateRange.start}
                onChange={e => setDateRange(p => ({ ...p, start: e.target.value }))}
                className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white" />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">End Date</label>
              <input type="date" value={dateRange.end}
                onChange={e => setDateRange(p => ({ ...p, end: e.target.value }))}
                className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white" />
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700 dark:border-green-800 dark:bg-green-900/20 dark:text-green-300">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {reportTypes.map(report => (
          <Card key={report.id} className="hover:shadow-lg transition-shadow">
            <CardContent className="p-6">
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  <div className="p-2 bg-gray-50 dark:bg-gray-800 rounded-lg">
                    <report.icon className={`h-6 w-6 ${report.color}`} />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-white">{report.title}</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{report.desc}</p>
                  </div>
                </div>
              </div>
              <div className="mt-4 flex gap-2">
                <Button size="sm" onClick={() => handleGenerate(report.id, report.title)}
                  disabled={generating === report.id}
                  loading={generating === report.id}
                  className="bg-blue-600 hover:bg-blue-700 text-white">
                  {generating === report.id ? 'Generating...' : (
                    <><Download className="h-3 w-3 mr-1" /> Generate CSV</>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
