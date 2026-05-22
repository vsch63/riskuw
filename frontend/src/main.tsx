import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, theme } from 'antd'
import App from './App'
import './styles/globals.css'

const darkToken = {
  colorPrimary: '#00d4aa',
  colorBgBase: '#060d1f',
  colorBgContainer: '#0f2044',
  colorBgElevated: '#0f2044',
  colorBorder: 'rgba(255,255,255,0.12)',
  colorText: '#ffffff',
  colorTextSecondary: '#94a3b8',
  colorTextPlaceholder: '#475569',
  borderRadius: 8,
  fontFamily: "'DM Sans', sans-serif",
  colorError: '#ef4444',
  colorSuccess: '#22c55e',
  colorWarning: '#f59e0b',
  colorInfo: '#00d4aa',
  colorLink: '#00d4aa',
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: darkToken,
        components: {
          Button: {
            primaryColor: '#060d1f',
          },
          Input: {
            colorBgContainer: 'rgba(255,255,255,0.05)',
          },
          Select: {
            colorBgContainer: 'rgba(255,255,255,0.05)',
            colorBgElevated: '#0f2044',
          },
          InputNumber: {
            colorBgContainer: 'rgba(255,255,255,0.05)',
          },
          DatePicker: {
            colorBgContainer: 'rgba(255,255,255,0.05)',
            colorBgElevated: '#0f2044',
          },
          Form: {
            labelColor: '#94a3b8',
            labelFontSize: 12,
          },
          Collapse: {
            colorBgContainer: 'rgba(255,255,255,0.02)',
            headerBg: 'rgba(255,255,255,0.03)',
          },
          Table: {
            colorBgContainer: 'rgba(255,255,255,0.02)',
            headerBg: 'rgba(255,255,255,0.06)',
            rowHoverBg: 'rgba(0,212,170,0.06)',
          },
          Tag: {
            colorBgBase: 'transparent',
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
