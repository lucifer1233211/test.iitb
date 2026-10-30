import { redirect } from 'next/navigation'

export default function HomePage() {
  // Redirect to login page for now
  // In a real application, you might want to show a landing page
  // or redirect to dashboard if user is already authenticated
  redirect('/login')
}