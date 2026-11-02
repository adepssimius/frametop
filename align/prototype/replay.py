# Replays run 3's lean pass through the live solver, comparing its error estimate with the actual error.
import json,pickle,sys,os
import numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import live_core as L
D=os.path.dirname(os.path.abspath(__file__)); R=D+'/run3'
cal=L.load_calib(); mk=json.load(open(D+'/marker.json')); pitch=json.load(open(D+'/panel.json'))['pitch_mm']/1000
P=np.loadtxt(R+'/poses.csv',delimiter=','); ps=L.Poses(); ps.add_rows(P)
obs=[o for o in pickle.load(open(R+'/obs.pkl','rb')) if o['ph']=='lean']
obs.sort(key=lambda o:o['t'])
print('frames',len(obs))
full=L.Solver(cal,mk,pitch)
for o in obs:
    if o['tags']: full.add(o['cam'],ps.at(o['t']-L.OFF_NS),o['tags'])
f=full.solve(max_frames=400); ref=full.corners(f['q']); print('reference sd %.2f mm rms %.2f frames %d'%(f['sd_mm'],f['rms'],f['frames']))
rows=[]
for start in np.arange(0,28,4.0):
    t0=obs[0]['t']+start*1e9
    S=L.Solver(cal,mk,pitch); next_t=0.5
    w=[o for o in obs if t0<=o['t']<t0+10e9]
    for o in w:
        if o['tags']: S.add(o['cam'],ps.at(o['t']-L.OFF_NS),o['tags'])
        el=(o['t']-t0)/1e9
        if el>=next_t and S.obs:
            r=S.solve()
            if r:
                err=np.linalg.norm(S.corners(r['q'])-ref,axis=1).max()*1000
                rows.append((start,el,r['sd_mm'],err,r['change_mm']))
            next_t+=0.5
a=np.array(rows)
print('points',len(a))
for lo,hi in((0,1),(1,2),(2,3),(3,5),(5,10)):
    m=(a[:,1]>=lo)&(a[:,1]<hi)
    if m.sum(): print(' %2d-%2ds: estimate sd median %.2f, actual worst-corner median %.1f p90 %.1f, ratio actual/estimate median %.1f'%(lo,hi,np.median(a[m,2]),np.median(a[m,3]),np.percentile(a[m,3],90),np.median(a[m,3]/a[m,2])))
print('overall ratio p50 %.1f p90 %.1f; corr(log est,log act) %.2f'%(np.median(a[:,3]/a[:,2]),np.percentile(a[:,3]/a[:,2],90),np.corrcoef(np.log(a[:,2]),np.log(a[:,3]))[0,1]))
for th in(3,5,8):
    # at the first moment est*K<th in each window
    for K in(6,10,15):
        got=[];t=[]
        for start in np.unique(a[:,0]):
            s=a[a[:,0]==start]; hit=s[s[:,2]*K<th]
            if len(hit): got.append(hit[0,3]); t.append(hit[0,1])
        if got: print(' threshold %d mm K=%d: triggered %d windows, median %.1fs, actual worst-corner median %.1f max %.1f'%(th,K,len(got),np.median(t),np.median(got),max(got)))
