#ifndef _COS_IDL_SCHED_H
#define _COS_IDL_SCHED_H

#include "cidl_gen.h"

service_global_info = {
	service		     = sched,

        desc_close_self_only = true,
        desc_dep_create_none = true,
        desc_global	     = true,
        desc_block	     = true,
        desc_has_data	     = false,
        resc_has_data	     = true,
};

sm_creation(sched_create_thd);
sm_transition(sched_create_thd, sched_block);
sm_transition(sched_block, sched_wakeup);
sm_transition(sched_wakeup, sched_block);

sm_transition(sched_create_thd, sched_component_take);
sm_transition(sched_component_take, sched_component_release);
sm_transition(sched_component_release, sched_component_take);

sm_transition(sched_create_thd, sched_timestamp);
sm_transition(sched_timestamp, sched_timeout);
sm_transition(sched_timeout, sched_timestamp);

sm_block(sched_block);
sm_wakeup(sched_wakeup);

desc_data_retval(int, thdid)
sched_create_thd(spdid_t spdid, 
		 u32_t sched_param0, 
		 u32_t sched_param1, 
		 u32_t sched_param2);

int 
sched_block(spdid_t spdid, 
	    u16_t desc_data(dependency_thd));

int 
sched_wakeup(spdid_t spdid, 
	     u16_t thdid);

int
sched_component_take(spdid_t spdid);

int
sched_component_release(spdid_t spdid);

int
sched_timeout(spdid_t spdid, 
	      ul_t desc_data(amnt));

resc_data(ul_t, timertick)
sched_timestamp(void);

#endif /* _COS_IDL_SCHED_H */
