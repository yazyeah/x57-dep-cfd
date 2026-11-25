"""Small closed-form tests. This creates QA evidence only, never aircraft results."""
from pathlib import Path
import json
import numpy as np
from map_cfd_shell_loads import nearest_triangle,scatter,motor_reaction,resultant
from mapdl_static_results import equilibrium
from prepare_mapdl_shell import OUT

def prove():
    # A unit-area triangle has a 12 Pa inward pressure and a known tangential
    # traction. An offset of 0.013 m deliberately exercises the arm correction.
    X=np.array([[0.,0.,0.],[2.,0.,0.],[0.,1.,0.]])
    pts=np.array([[2/3,1/3,.013]])
    F=np.array([[3.,-2.,-12.]])
    face,wgt,dist,dot=nearest_triangle(pts,np.array([[0.,0.,1.]]),X,np.array([[0,1,2]]))
    assert np.allclose(wgt,1/3) and np.allclose(dist,.013) and np.allclose(dot,1)
    loads=np.zeros((3,6));scatter(pts,F,X,face,wgt,loads)
    expected=np.r_[F[0],np.cross(pts[0],F[0])]
    mapped=resultant(X,loads[:,:3],loads[:,3:]);assert np.allclose(mapped,expected)
    u0=np.array([.4,-.1,.07]);rotation=np.array([.12,.09,-.2])
    work=(loads[:,:3]*(u0+np.cross(rotation,X))).sum()+(loads[:,3:]*rotation).sum()
    face_work=(F*(u0+np.cross(rotation,pts))).sum()
    assert np.isclose(work,face_work)
    angles=np.arange(11)*2*np.pi/11;center=np.array([.2,-.5,1.0])
    mount=center+np.column_stack((np.zeros(11),.08*np.cos(angles),.08*np.sin(angles)))
    arm=center+[-.19,.02,-.005];force=np.array([-120.,4.,0.]);torque=np.array([-5.,0.,0.])
    mf=motor_reaction(mount,np.arange(len(mount)),arm,force,torque)
    motor_reference=np.r_[force,torque+np.cross(arm,force)]
    motor_error=resultant(mount,mf)-motor_reference
    assert np.linalg.norm(motor_error)<1e-10
    root=np.array([[-.4,.2,0.]])
    input_wrench=mapped+motor_reference
    Rf=-input_wrench[:3];Rm=-input_wrench[3:]-np.cross(root[0],Rf)
    ra=np.r_[Rf,Rm][None,:]
    good=equilibrium(root,ra,input_wrench,180.,120.)
    wrong=ra.copy();wrong[0,0]+=2.
    assert good['passed'] and not equilibrium(root,wrong,input_wrench,180.,120.)['passed']
    result={'classification':'Analytical fixture only; no Fluent data, no MAPDL solution, and no aircraft result.',
            'uniform_pressure_shear_triangle_reference_wrench':expected.tolist(),'transferred_wrench':mapped.tolist(),
            'wrench_residual':(mapped-expected).tolist(),'rigid_virtual_work_residual_J':float(work-face_work),
            'off_axis_mount_absolute_force_moment_residual':motor_error.tolist(),
            'balanced_reaction_fixture':good,'intentionally_unbalanced_fixture_rejected':True}
    path=OUT/'preflight';path.mkdir(exist_ok=True)
    (path/'analytic_transfer_qa.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
if __name__=='__main__':prove()
