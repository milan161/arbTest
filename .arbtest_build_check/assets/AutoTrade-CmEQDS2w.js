import{B as e,F as t,I as n,Mt as r,Pt as i,R as a,S as o,T as s,X as c,_ as l,b as u,c as d,h as f,it as p,m,ot as h,pt as g,ut as _,v,x as y}from"./warn-Cq0iJHZk.js";import{J as b,K as x,N as S,P as C,U as w,W as T,Y as E,i as D,n as O,q as k,t as A,z as j}from"./Icon-CIeviPh2.js";import{a as M,c as N,h as P,l as F,p as I,t as L,v as R,y as z}from"./Button-DzOedRsZ.js";import{Ct as B,Et as V,a as H,f as U,ht as ee,r as te,u as W}from"./Tooltip-Boyh5BSA.js";import{i as G,n as K,r as ne,t as re}from"./trash-2-CprU33Xn.js";import{t as ie}from"./InputNumber-CDG1SfSZ.js";import{t as ae}from"./plus-DehWmLl4.js";import{Cr as q,Sr as J,_n as Y,_r as X,dn as oe,fn as se,fr as ce,gn as le,gr as ue,hn as de,lr as fe,mn as pe,pn as me,pr as he,sr as ge,un as _e,ur as Z,vr as ve,xr as ye,yr as be}from"./index-Ba4OekXv.js";var xe={buttonHeightSmall:`14px`,buttonHeightMedium:`18px`,buttonHeightLarge:`22px`,buttonWidthSmall:`14px`,buttonWidthMedium:`18px`,buttonWidthLarge:`22px`,buttonWidthPressedSmall:`20px`,buttonWidthPressedMedium:`24px`,buttonWidthPressedLarge:`28px`,railHeightSmall:`18px`,railHeightMedium:`22px`,railHeightLarge:`26px`,railWidthSmall:`32px`,railWidthMedium:`40px`,railWidthLarge:`48px`};function Se(e){let{primaryColor:t,opacityDisabled:n,borderRadius:r,textColor3:i}=e;return Object.assign(Object.assign({},xe),{iconColor:i,textColor:`white`,loadingColor:t,opacityDisabled:n,railColor:`rgba(0, 0, 0, .14)`,railColorActive:t,buttonBoxShadow:`0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)`,buttonColor:`#FFF`,railBorderRadiusSmall:r,railBorderRadiusMedium:r,railBorderRadiusLarge:r,buttonBorderRadiusSmall:r,buttonBorderRadiusMedium:r,buttonBorderRadiusLarge:r,boxShadowFocus:`0 0 0 2px ${j(t,{alpha:.2})}`})}var Ce={name:`Switch`,common:O,self:Se},we=T(`switch`,`
 height: var(--n-height);
 min-width: var(--n-width);
 vertical-align: middle;
 user-select: none;
 -webkit-user-select: none;
 display: inline-flex;
 outline: none;
 justify-content: center;
 align-items: center;
`,[x(`children-placeholder`,`
 height: var(--n-rail-height);
 display: flex;
 flex-direction: column;
 overflow: hidden;
 pointer-events: none;
 visibility: hidden;
 `),x(`rail-placeholder`,`
 display: flex;
 flex-wrap: none;
 `),x(`button-placeholder`,`
 width: calc(1.75 * var(--n-rail-height));
 height: var(--n-rail-height);
 `),T(`base-loading`,`
 position: absolute;
 top: 50%;
 left: 50%;
 transform: translateX(-50%) translateY(-50%);
 font-size: calc(var(--n-button-width) - 4px);
 color: var(--n-loading-color);
 transition: color .3s var(--n-bezier);
 `,[N({left:`50%`,top:`50%`,originalTransform:`translateX(-50%) translateY(-50%)`})]),x(`checked, unchecked`,`
 transition: color .3s var(--n-bezier);
 color: var(--n-text-color);
 box-sizing: border-box;
 position: absolute;
 white-space: nowrap;
 top: 0;
 bottom: 0;
 display: flex;
 align-items: center;
 line-height: 1;
 `),x(`checked`,`
 right: 0;
 padding-right: calc(1.25 * var(--n-rail-height) - var(--n-offset));
 `),x(`unchecked`,`
 left: 0;
 justify-content: flex-end;
 padding-left: calc(1.25 * var(--n-rail-height) - var(--n-offset));
 `),w(`&:focus`,[x(`rail`,`
 box-shadow: var(--n-box-shadow-focus);
 `)]),k(`round`,[x(`rail`,`border-radius: calc(var(--n-rail-height) / 2);`,[x(`button`,`border-radius: calc(var(--n-button-height) / 2);`)])]),b(`disabled`,[b(`icon`,[k(`rubber-band`,[k(`pressed`,[x(`rail`,[x(`button`,`max-width: var(--n-button-width-pressed);`)])]),x(`rail`,[w(`&:active`,[x(`button`,`max-width: var(--n-button-width-pressed);`)])]),k(`active`,[k(`pressed`,[x(`rail`,[x(`button`,`left: calc(100% - var(--n-offset) - var(--n-button-width-pressed));`)])]),x(`rail`,[w(`&:active`,[x(`button`,`left: calc(100% - var(--n-offset) - var(--n-button-width-pressed));`)])])])])])]),k(`active`,[x(`rail`,[x(`button`,`left: calc(100% - var(--n-button-width) - var(--n-offset))`)])]),x(`rail`,`
 overflow: hidden;
 height: var(--n-rail-height);
 min-width: var(--n-rail-width);
 border-radius: var(--n-rail-border-radius);
 cursor: pointer;
 position: relative;
 transition:
 opacity .3s var(--n-bezier),
 background .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 background-color: var(--n-rail-color);
 `,[x(`button-icon`,`
 color: var(--n-icon-color);
 transition: color .3s var(--n-bezier);
 font-size: calc(var(--n-button-height) - 4px);
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 display: flex;
 justify-content: center;
 align-items: center;
 line-height: 1;
 `,[N()]),x(`button`,`
 align-items: center; 
 top: var(--n-offset);
 left: var(--n-offset);
 height: var(--n-button-height);
 width: var(--n-button-width-pressed);
 max-width: var(--n-button-width);
 border-radius: var(--n-button-border-radius);
 background-color: var(--n-button-color);
 box-shadow: var(--n-button-box-shadow);
 box-sizing: border-box;
 cursor: inherit;
 content: "";
 position: absolute;
 transition:
 background-color .3s var(--n-bezier),
 left .3s var(--n-bezier),
 opacity .3s var(--n-bezier),
 max-width .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 `)]),k(`active`,[x(`rail`,`background-color: var(--n-rail-color-active);`)]),k(`loading`,[x(`rail`,`
 cursor: wait;
 `)]),k(`disabled`,[x(`rail`,`
 cursor: not-allowed;
 opacity: .5;
 `)])]),Te=Object.assign(Object.assign({},D.props),{size:String,value:{type:[String,Number,Boolean],default:void 0},loading:Boolean,defaultValue:{type:[String,Number,Boolean],default:!1},disabled:{type:Boolean,default:void 0},round:{type:Boolean,default:!0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],checkedValue:{type:[String,Number,Boolean],default:!0},uncheckedValue:{type:[String,Number,Boolean],default:!1},railStyle:Function,rubberBand:{type:Boolean,default:!0},spinProps:Object,onChange:[Function,Array]}),Q,Ee=o({name:`Switch`,props:Te,slots:Object,setup(e){Q===void 0&&(Q=typeof CSS<`u`?CSS.supports===void 0?!1:CSS.supports(`width`,`max(1px)`):!0);let{mergedClsPrefixRef:t,inlineThemeDisabled:n,mergedComponentPropsRef:r}=C(e),i=D(`Switch`,`-switch`,we,Ce,e,t),a=I(e,{mergedSize(t){return e.size===void 0?t?t.mergedSize.value:r?.value?.Switch?.size||`medium`:e.size}}),{mergedSizeRef:o,mergedDisabledRef:s}=a,c=h(e.defaultValue),l=ee(_(e,`value`),c),u=m(()=>l.value===e.checkedValue),d=h(!1),f=h(!1),p=m(()=>{let{railStyle:t}=e;if(t)return t({focused:f.value,checked:u.value})});function g(t){let{"onUpdate:value":n,onChange:r,onUpdateValue:i}=e,{nTriggerFormInput:o,nTriggerFormChange:s}=a;n&&z(n,t),i&&z(i,t),r&&z(r,t),c.value=t,o(),s()}function v(){let{nTriggerFormFocus:e}=a;e()}function y(){let{nTriggerFormBlur:e}=a;e()}function b(){e.loading||s.value||(l.value===e.checkedValue?g(e.uncheckedValue):g(e.checkedValue))}function x(){f.value=!0,v()}function w(){f.value=!1,y(),d.value=!1}function T(t){e.loading||s.value||t.key===` `&&(l.value===e.checkedValue?g(e.uncheckedValue):g(e.checkedValue),d.value=!1)}function O(t){e.loading||s.value||t.key===` `&&(t.preventDefault(),d.value=!0)}let k=m(()=>{let{value:e}=o,{self:{opacityDisabled:t,railColor:n,railColorActive:r,buttonBoxShadow:a,buttonColor:s,boxShadowFocus:c,loadingColor:l,textColor:u,iconColor:d,[E(`buttonHeight`,e)]:f,[E(`buttonWidth`,e)]:p,[E(`buttonWidthPressed`,e)]:m,[E(`railHeight`,e)]:h,[E(`railWidth`,e)]:g,[E(`railBorderRadius`,e)]:_,[E(`buttonBorderRadius`,e)]:v},common:{cubicBezierEaseInOut:y}}=i.value,b,x,S;return Q?(b=`calc((${h} - ${f}) / 2)`,x=`max(${h}, ${f})`,S=`max(${g}, calc(${g} + ${f} - ${h}))`):(b=V((B(h)-B(f))/2),x=V(Math.max(B(h),B(f))),S=B(h)>B(f)?g:V(B(g)+B(f)-B(h))),{"--n-bezier":y,"--n-button-border-radius":v,"--n-button-box-shadow":a,"--n-button-color":s,"--n-button-width":p,"--n-button-width-pressed":m,"--n-button-height":f,"--n-height":x,"--n-offset":b,"--n-opacity-disabled":t,"--n-rail-border-radius":_,"--n-rail-color":n,"--n-rail-color-active":r,"--n-rail-height":h,"--n-rail-width":g,"--n-width":S,"--n-box-shadow-focus":c,"--n-loading-color":l,"--n-text-color":u,"--n-icon-color":d}}),A=n?S(`switch`,m(()=>o.value[0]),k,e):void 0;return{handleClick:b,handleBlur:w,handleFocus:x,handleKeyup:T,handleKeydown:O,mergedRailStyle:p,pressed:d,mergedClsPrefix:t,mergedValue:l,checked:u,mergedDisabled:s,cssVars:n?void 0:k,themeClass:A?.themeClass,onRender:A?.onRender}},render(){let{mergedClsPrefix:e,mergedDisabled:t,checked:n,mergedRailStyle:r,onRender:i,$slots:a}=this;i?.();let{checked:o,unchecked:c,icon:l,"checked-icon":u,"unchecked-icon":d}=a,f=!(P(l)&&P(u)&&P(d));return s(`div`,{role:`switch`,"aria-checked":n,class:[`${e}-switch`,this.themeClass,f&&`${e}-switch--icon`,n&&`${e}-switch--active`,t&&`${e}-switch--disabled`,this.round&&`${e}-switch--round`,this.loading&&`${e}-switch--loading`,this.pressed&&`${e}-switch--pressed`,this.rubberBand&&`${e}-switch--rubber-band`],tabindex:this.mergedDisabled?void 0:0,style:this.cssVars,onClick:this.handleClick,onFocus:this.handleFocus,onBlur:this.handleBlur,onKeyup:this.handleKeyup,onKeydown:this.handleKeydown},s(`div`,{class:`${e}-switch__rail`,"aria-hidden":`true`,style:r},R(o,t=>R(c,n=>t||n?s(`div`,{"aria-hidden":!0,class:`${e}-switch__children-placeholder`},s(`div`,{class:`${e}-switch__rail-placeholder`},s(`div`,{class:`${e}-switch__button-placeholder`}),t),s(`div`,{class:`${e}-switch__rail-placeholder`},s(`div`,{class:`${e}-switch__button-placeholder`}),n)):null)),s(`div`,{class:`${e}-switch__button`},R(l,t=>R(u,n=>R(d,r=>s(F,null,{default:()=>this.loading?s(M,Object.assign({key:`loading`,clsPrefix:e,strokeWidth:20},this.spinProps)):this.checked&&(n||t)?s(`div`,{class:`${e}-switch__button-icon`,key:n?`checked-icon`:`icon`},n||t):!this.checked&&(r||t)?s(`div`,{class:`${e}-switch__button-icon`,key:r?`unchecked-icon`:`icon`},r||t):null})))),R(o,t=>t&&s(`div`,{key:`checked`,class:`${e}-switch__checked`},t)),R(c,t=>t&&s(`div`,{key:`unchecked`,class:`${e}-switch__unchecked`},t)))))}}),De=Z(`ban`,[[`circle`,{cx:`12`,cy:`12`,r:`10`,key:`1mglay`}],[`path`,{d:`M4.929 4.929 19.07 19.071`,key:`196cmz`}]]),$=Z(`power`,[[`path`,{d:`M12 2v10`,key:`mnfbl`}],[`path`,{d:`M18.4 6.6a9 9 0 1 1-12.77.04`,key:`obofu9`}]]),Oe=Z(`square-pen`,[[`path`,{d:`M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7`,key:`1m0v6g`}],[`path`,{d:`M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z`,key:`ohrbg2`}]]),ke={class:`auto-trade-container`},Ae={class:`flex-between`},je={class:`flex-center gap-4`},Me={class:`log-terminal`},Ne={key:0,class:`log-empty`},Pe={class:`l-time`},Fe={class:`l-msg`},Ie={class:`flex-end gap-2 mt-4`},Le=_e(o({__name:`AutoTrade`,setup(o){let m=ve(),_=ce(),b=h(!1),x=h(!1),S=h([]),C=h([]),w=h(!1),T=h(null),E=null,D=p({name:``,target:``,type:`code`,indicator:`discount`,threshold:.7,action:`OPEN`}),O=async()=>{b.value=(await de()).data.running},k=async()=>{try{let e=(await me()).data.rules||[];e.sort((e,t)=>!!t.enabled-+!!e.enabled),S.value=e}catch{m.error(`加载规则失败`)}},j=()=>{T.value=null,Object.assign(D,{name:``,target:``,indicator:`discount`,threshold:.7,action:`OPEN`}),w.value=!0},M=e=>{T.value=e.id,Object.assign(D,e),w.value=!0},N=async()=>{try{T.value?await Y(T.value,D):await oe(D),m.success(`规则已更新`),w.value=!1,k()}catch{m.error(`保存失败`)}},P=async e=>{try{await se(e),m.warning(`规则已删除`),k()}catch{m.error(`删除失败`)}},F=async()=>{C.value=(await pe()).data.logs},I=()=>{O(),k(),F()},R=async()=>{x.value=!0;let e=b.value?`stop`:`start`;try{b.value=(await le(e)).data.running,m.success(b.value?`信号检测已开启`:`信号检测已停止`)}finally{x.value=!1}},z=async(e,t)=>{try{e.enabled=t,await Y(e.id,{enabled:t}),m.info(`${e.name} 已${t?`开启`:`关闭`}`)}catch{m.error(`操作失败`)}},B=[{title:`开关`,key:`enabled`,width:60,align:`center`,render(e){return s(Ee,{value:e.enabled,size:`small`,onUpdateValue:t=>z(e,t)})}},{title:`规则名称`,key:`name`,render:e=>s(he,{strong:!0},{default:()=>e.name})},{title:`监控对象`,key:`target`,width:100,align:`center`,className:`col-target`},{title:`触发条件`,key:`logic`,width:180,align:`center`,render(e){let t=e.indicator===`discount`,n=e.action===`OPEN`||e.action===`BUY`;return s(`div`,[s(U,{type:t?`success`:`error`,size:`tiny`,ghost:!0},{default:()=>t?`折价`:`溢价`}),s(`span`,{style:`margin-left: 5px`},`> ${e.threshold}%`),s(`br`),s(U,{type:n?`info`:`warning`,size:`tiny`,ghost:!0,style:`margin-top: 2px`},{default:()=>n?`开仓（买LOF+空ETF）`:`平仓（卖LOF+平ETF）`})])}},{title:`操作`,key:`actions`,width:150,align:`center`,render(e){return s(G,{justify:`center`},{default:()=>[s(L,{quaternary:!0,circle:!0,size:`tiny`,onClick:()=>M(e)},{default:()=>s(A,null,{default:()=>s(Oe)})}),s(L,{quaternary:!0,circle:!0,size:`tiny`,type:`error`,onClick:()=>P(e.id)},{default:()=>s(A,null,{default:()=>s(re)})}),s(L,{quaternary:!0,circle:!0,size:`tiny`,type:`error`,onClick:()=>_.push({path:`/lazymode`,query:{code:e.target,name:e.name}})},{default:()=>s(A,null,{default:()=>s(De)})})]})}}];return t(()=>{I(),E=setInterval(I,3e3)}),n(()=>{E&&clearInterval(E)}),(t,n)=>(a(),v(`div`,ke,[y(g(ue),{cols:24,"x-gap":12,"y-gap":12},{default:c(()=>[y(g(X),{span:24},{default:c(()=>[y(g(H),{class:`shadow-soft header-card`},{default:c(()=>[f(`div`,Ae,[f(`div`,je,[y(g(A),{size:`32`,color:`#3b82f6`},{default:c(()=>[y(g(ge))]),_:1}),n[7]||=f(`div`,null,[f(`div`,{class:`header-title`},`策略规则`),f(`div`,{class:`header-subtitle`})],-1),y(g(U),{bordered:!1,round:``,type:b.value?`success`:`error`,class:`status-badge`},{icon:c(()=>[y(g(A),null,{default:c(()=>[y(g(fe))]),_:1})]),default:c(()=>[u(` `+i(b.value?`信号检测: 运行中`:`信号检测: 停止`),1)]),_:1},8,[`type`])]),y(g(G),null,{default:c(()=>[y(g(L),{type:b.value?`error`:`success`,secondary:``,onClick:R,loading:x.value},{icon:c(()=>[y(g(A),null,{default:c(()=>[y(g($))]),_:1})]),default:c(()=>[u(` `+i(b.value?`停止检测`:`开启检测`),1)]),_:1},8,[`type`,`loading`])]),_:1})])]),_:1})]),_:1}),y(g(X),{span:10},{default:c(()=>[y(g(H),{title:`信号日志`,bordered:!1,class:`shadow-soft full-height`},{default:c(()=>[f(`div`,Me,[C.value.length===0?(a(),v(`div`,Ne,`等待信号扫描触发...`)):l(``,!0),(a(!0),v(d,null,e(C.value,(e,t)=>(a(),v(`div`,{key:t,class:`log-line`},[f(`span`,Pe,`[`+i(e.time)+`]`,1),f(`span`,{class:r([`l-level`,e.level.toLowerCase()])},`[`+i(e.level)+`]`,3),f(`span`,Fe,i(e.message),1)]))),128))])]),_:1})]),_:1}),y(g(X),{span:14},{default:c(()=>[y(g(H),{title:`活跃套利策略`,bordered:!1,class:`shadow-soft full-height`},{"header-extra":c(()=>[y(g(L),{type:`primary`,size:`small`,onClick:j},{icon:c(()=>[y(g(A),null,{default:c(()=>[y(g(ae))]),_:1})]),default:c(()=>[n[8]||=u(` 新增规则 `,-1)]),_:1})]),default:c(()=>[y(g(ye),{columns:B,data:S.value,size:`small`,bordered:``,pagination:{pageSize:8}},null,8,[`data`])]),_:1})]),_:1})]),_:1}),y(g(be),{show:w.value,"onUpdate:show":n[6]||=e=>w.value=e,preset:`card`,title:T.value?`编辑规则`:`新增规则`,style:{width:`550px`}},{default:c(()=>[y(g(ne),{model:D,"label-placement":`left`,"label-width":`100`},{default:c(()=>[y(g(K),{label:`策略名称`},{default:c(()=>[y(g(W),{value:D.name,"onUpdate:value":n[0]||=e=>D.name=e,placeholder:`起个直观的名字`},null,8,[`value`])]),_:1}),y(g(K),{label:`监视对象`},{default:c(()=>[y(g(W),{value:D.target,"onUpdate:value":n[1]||=e=>D.target=e,placeholder:`基金代码 (162411) 或 分类 (黄金原油)`},null,8,[`value`])]),_:1}),y(g(K),{label:`触发条件`},{default:c(()=>[y(g(J),{value:D.indicator,"onUpdate:value":n[2]||=e=>D.indicator=e},{default:c(()=>[y(g(q),{value:`discount`},{default:c(()=>[...n[9]||=[u(`折价`,-1)]]),_:1}),y(g(q),{value:`premium`},{default:c(()=>[...n[10]||=[u(`溢价`,-1)]]),_:1})]),_:1},8,[`value`]),y(g(ie),{value:D.threshold,"onUpdate:value":n[3]||=e=>D.threshold=e,precision:2,style:{width:`120px`,"margin-left":`12px`}},null,8,[`value`]),n[11]||=f(`span`,{style:{"margin-left":`8px`}},`%`,-1)]),_:1}),y(g(K),{label:`动作方向`},{default:c(()=>[y(g(te),{value:D.action,"onUpdate:value":n[4]||=e=>D.action=e,options:[{label:`做多（买LOF+空ETF）`,value:`OPEN`},{label:`平仓（卖LOF+平ETF）`,value:`CLOSE`}]},null,8,[`value`])]),_:1}),f(`div`,Ie,[y(g(L),{onClick:n[5]||=e=>w.value=!1},{default:c(()=>[...n[12]||=[u(`取消`,-1)]]),_:1}),y(g(L),{type:`primary`,onClick:N},{default:c(()=>[u(i(T.value?`更新规则`:`保存`),1)]),_:1})])]),_:1},8,[`model`])]),_:1},8,[`show`,`title`])]))}}),[[`__scopeId`,`data-v-1cfa66b7`]]);export{Le as default};