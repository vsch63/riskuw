with open('/opt/riskuw/frontend/src/pages/EvaluatePage.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''            <p style={{ color: 'var(--slate-500)', fontSize: 13, marginBottom: 24 }}>
              Evaluate base plan + riders in a single underwriting call
            </p>'''

new = '''            <p style={{ color: 'var(--slate-500)', fontSize: 13, marginBottom: 16 }}>
              Evaluate base plan + riders in a single underwriting call
            </p>

            {/* Info banner — uses shared form */}
            <div style={{ background: 'rgba(0,212,170,0.06)', border: '1px solid rgba(0,212,170,0.2)',
              borderRadius: 8, padding: '10px 14px', marginBottom: 20,
              display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 18 }}>ℹ️</span>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#00d4aa' }}>Uses applicant details from the Evaluate Application tab</div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
                  Fill in applicant age, gender, medical details and upload documents in the
                  <strong style={{ color: '#9ca3af' }}> Evaluate Application</strong> tab first,
                  then come here to select base plan and riders.
                </div>
              </div>
            </div>

            {/* Quick applicant summary from form */}
            {(() => {
              const v = form.getFieldsValue()
              if (!v.age && !v.gender) return null
              return (
                <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)',
                  borderRadius: 8, padding: '10px 14px', marginBottom: 16,
                  display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  {v.applicant_ref && <div><span style={{fontSize:10,color:'#6b7280'}}>REF </span><span style={{fontSize:12,color:'#e2e8f0',fontFamily:'var(--font-mono)'}}>{v.applicant_ref}</span></div>}
                  {v.age && <div><span style={{fontSize:10,color:'#6b7280'}}>AGE </span><span style={{fontSize:12,color:'#e2e8f0'}}>{v.age}</span></div>}
                  {v.gender && <div><span style={{fontSize:10,color:'#6b7280'}}>GENDER </span><span style={{fontSize:12,color:'#e2e8f0'}}>{v.gender}</span></div>}
                  {v.tobacco_status && <div><span style={{fontSize:10,color:'#6b7280'}}>TOBACCO </span><span style={{fontSize:12,color:'#e2e8f0'}}>{v.tobacco_status}</span></div>}
                  {v.annual_income && <div><span style={{fontSize:10,color:'#6b7280'}}>INCOME </span><span style={{fontSize:12,color:'#e2e8f0'}}>₹{new Intl.NumberFormat('en-IN').format(v.annual_income)}</span></div>}
                  {!v.age && <div style={{fontSize:11,color:'#f59e0b'}}>⚠ No applicant details — fill Evaluate Application tab first</div>}
                </div>
              )
            })()}'''

if old in content:
    content = content.replace(old, new)
    with open('/opt/riskuw/frontend/src/pages/EvaluatePage.tsx', 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS")
else:
    print("ERROR")
    idx = content.find("Evaluate base plan + riders")
    print(repr(content[max(0,idx-50):idx+150]))
